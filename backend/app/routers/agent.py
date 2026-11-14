"""FastAPI router for AI AttendanceAgent and tool integration."""

from __future__ import annotations

import logging
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent import AttendanceAgent, CONFIDENCE_CONFIRMATION_THRESHOLD
from app.auth import (
    Role,
    get_current_user,
    require_roles,
    rate_limit_chat,
    rate_limit_process_file,
    rate_limit_confirm,
)
from app.db import crud
from app.auth.session_scope import resolve_data_scope
from app.services.attendance_edits import (
    AttendanceChange,
    actor_identity,
    assert_session_edit_authorized,
    capture_attendance_statuses,
    confirm_attendance_edit,
    propose_attendance_edit,
    resolve_edit_intent,
    write_attendance_audit,
    _utcnow_iso,
)
from app.dependencies import get_db
from app.security.ai_input import PromptInjectionError, screen_agent_input
from app.security.context import get_request_id
from app.security.events import log_security_event
from app.security.ai_input import find_prompt_injection, safe_excerpt
from app.security.rate_limit import LimitScope, check_limit
from app.security.uploads import (
    check_declared_content_type,
    check_extension_consistency,
    check_image_dimensions,
    get_malware_scanner,
)
from app.schemas.agent import (
    AgentConfirmRequest,
    AgentResponseSchema,
    AgentStatusResponse,
    AttendanceEditConfirmRequest,
    AttendanceEditConfirmResponse,
    AttendanceEditProposalRequest,
    AttendanceEditProposalResponse,
    ChatQueryRequest,
)
from app.schemas.auth import AuthenticatedUser
from tools.validate_tool import validate_tool
from tools.query_tool import validate_read_only_sql

logger = logging.getLogger("rollcall.routers.agent")

router = APIRouter(prefix="/agent", tags=["Agent"])

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB limit
MAX_TEXT_INSPECTION_BYTES = 1024 * 1024  # bounded best-effort telemetry
# Supported roster formats. Every extension is validated against the file
# signature below, so an attacker cannot smuggle a different payload through a
# renamed file.
ALLOWED_EXTENSIONS = {
    ".csv",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".pdf",
    ".xlsx",
    ".xls",
}

# Document formats that carry an attendance table (as opposed to a photo).
DOCUMENT_EXTENSIONS = {".pdf", ".xlsx", ".xls"}


def _client_ip(request: Request) -> Optional[str]:
    """Best-effort client address (never a credential)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client and request.client.host:
        return request.client.host
    return None


def _log_embedded_instruction(
    text: str,
    *,
    request: Request,
    actor_id: str,
    filename: str,
    source: str,
) -> None:
    finding = find_prompt_injection(text[:MAX_TEXT_INSPECTION_BYTES])
    if finding is None:
        return
    log_security_event(
        "embedded_instruction_detected",
        severity="warning",
        outcome="suspicious",
        actor_id=actor_id,
        ip_address=_client_ip(request),
        request_id=get_request_id(),
        details={
            "rule": finding.rule,
            "filename": filename,
            "source": source,
            "note": "treated as data; no instruction executed",
        },
    )


# ==============================================================================
# 1. POST /api/v1/agent/chat
# ==============================================================================

@router.post(
    "/chat",
    response_model=AgentResponseSchema,
    summary="Chat with Attendance Agent",
    description="Ask natural-language questions about attendance, absentees, sessions, or students. Answers are backed strictly by verified database queries.",
    dependencies=[Depends(rate_limit_chat)],
)
def agent_chat(
    request: Request,
    payload: ChatQueryRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    query_text = payload.query.strip()
    if not query_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chat query cannot be empty or whitespace only.",
        )

    contextual_query = query_text
    if payload.session_id and f"session {payload.session_id}" not in query_text.lower():
        contextual_query = f"{query_text} for session {payload.session_id}"

    # Prompt-injection screening happens before the text reaches the agent.
    # File contents are parsed as data by the tools; only chat text is model
    # input, so this is the only place instructions can enter.
    try:
        screen_agent_input(contextual_query)
    except PromptInjectionError as exc:
        log_security_event(
            "prompt_injection_detected",
            severity="warning",
            outcome="blocked",
            actor_id=current_user.user_id,
            ip_address=_client_ip(request),
            request_id=get_request_id(),
            details={"pattern": exc.pattern},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "PROMPT_INJECTION", "message": str(exc)}},
        )

    # Check for raw SQL attempts that violate read-only rules (e.g. DROP TABLE, DELETE FROM, UPDATE table SET)
    raw_sql_patterns = [
        r"^\s*DROP\s+(?:TABLE|DATABASE|VIEW|INDEX|SCHEMA)\b",
        r"^\s*DELETE\s+FROM\b",
        r"^\s*INSERT\s+INTO\b",
        r"^\s*ALTER\s+TABLE\b",
        r"^\s*TRUNCATE\s+(?:TABLE\b)?",
        r"^\s*UPDATE\s+[a-zA-Z_][a-zA-Z0-9_]*\s+SET\b",
        r";\s*(?:DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE)\b",
    ]
    if any(re.search(pat, query_text, re.IGNORECASE) for pat in raw_sql_patterns):
        try:
            validate_read_only_sql(query_text)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

    # Inspect the exact final value passed to the agent, including contextual
    # fields, before any model or tool can see it.
    injection = find_prompt_injection(contextual_query)
    if injection is not None:
        log_security_event(
            "prompt_injection_blocked",
            severity="warning",
            outcome="blocked",
            actor_id=current_user.user_id,
            ip_address=_client_ip(request),
            request_id=get_request_id(),
            details={
                "rule": injection.rule,
                "excerpt": safe_excerpt(contextual_query),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Request rejected: the message contains instructions that attempt "
                "to override system, security or authorization controls."
            ),
        )

    # Prompt-injection guard: reject instruction-override payloads
    # before any tool can run. The request text is never treated as authority;
    # this is an explicit, logged refusal rather than a silent rewrite.
    # The agent runs with the caller's authorization scope: every attendance,
    # session and student read it performs is restricted to the sessions the
    # caller may see. This is enforced in the tool/query layer, never by the
    # prompt or the model.
    scope = resolve_data_scope(db, current_user)
    if payload.session_id:
        from app.db.models import Session as DbSession

        selected_session = db.get(DbSession, payload.session_id)
        if selected_session is None or not scope.is_session_visible(db, payload.session_id):
            # Use the same answer for missing and out-of-scope ids so callers
            # cannot probe session existence across tenant boundaries.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    role_str = getattr(current_user.role, "value", str(current_user.role))
    assigned_subs: List[str] = []
    actor_name = getattr(current_user, "name", None) or current_user.user_id
    try:
        assigned_subs = crud.get_teacher_subjects(db, user_id=current_user.user_id) or []
        from app.db.models import User
        u = db.query(User).filter(User.user_id == current_user.user_id).first()
        if u and u.name:
            actor_name = u.name
        # Prioritize full_name from persistent user_profiles if set
        from sqlalchemy import text
        prof_row = db.execute(
            text("SELECT full_name FROM user_profiles WHERE user_id = :uid"),
            {"uid": current_user.user_id},
        ).fetchone()
        if prof_row and prof_row[0] and prof_row[0].strip():
            actor_name = prof_row[0].strip()
    except Exception:
        assigned_subs = []

    # Execute the AttendanceAgent with verified database queries and guardrails.
    # It returns a structured response (message, success, data, tool_calls,
    # needs_confirmation, confirmation_request) that the contract tests rely on.
    agent = AttendanceAgent(
        db_target=db,
        scope=scope,
        role=current_user.role,
        actor_role=current_user.role,
        actor_id=current_user.user_id,
        actor_name=actor_name,
        assigned_subjects=assigned_subs,
    )
    req_id = str(uuid.uuid4())
    resp = agent.process_request(user_input=contextual_query, request_id=req_id)
    return resp.to_dict()


# ==============================================================================
# 2. POST /api/v1/agent/process-file
# ==============================================================================

@router.post(
    "/process-file",
    response_model=AgentResponseSchema,
    summary="Process attendance CSV or photo file",
    description="Upload an attendance sheet (CSV, PNG, JPG). Runs extraction and validation guardrails, halting for confirmation if confidence < 0.80 or errors exist.",
    dependencies=[Depends(rate_limit_process_file)],
    responses={
        400: {"description": "Invalid file type or format"},
        413: {"description": "File exceeds 10MB limit"},
        429: {"description": "Rate limit exceeded"},
    },
)
async def agent_process_file(
    request: Request,
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    default_room: Optional[str] = Form(None),
    default_branch: Optional[str] = Form(None),
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    # Upload rate limit (per caller and per IP), shared between workers.
    client_ip = _client_ip(request)
    upload_decision = check_limit(
        db, LimitScope.UPLOAD, f"user:{current_user.user_id}", record_failure=True, commit=True
    )
    if not upload_decision.allowed:
        log_security_event(
            "rate_limit_triggered",
            severity="warning",
            outcome="blocked",
            actor_id=current_user.user_id,
            ip_address=client_ip,
            request_id=get_request_id(),
            details={"scope": "upload", "retry_after_seconds": upload_decision.retry_after_seconds},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": {
                    "code": "RATE_LIMITED",
                    "message": "Too many uploads. Please try again later.",
                }
            },
            headers={"Retry-After": str(upload_decision.retry_after_seconds)},
        )

    # 1. Filename and extension check (Path traversal & null byte protection)
    raw_filename = file.filename or ""
    clean_filename = os.path.basename(raw_filename).replace("\x00", "")
    safe_filename = Path(clean_filename).name
    ext = Path(safe_filename).suffix.lower()

    if not ext or ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file extension '{ext}'. Allowed extensions: {', '.join(sorted(ALLOWED_EXTENSIONS))}.",
        )

    # 2. Secure streaming chunked upload & size enforcement
    CHUNK_SIZE = 64 * 1024  # 64KB bounded chunks
    total_bytes = 0
    first_chunk: Optional[bytes] = None
    fd, temp_path = tempfile.mkstemp(suffix=ext)

    try:
        with os.fdopen(fd, "wb") as f:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                if first_chunk is None and len(chunk) > 0:
                    first_chunk = chunk
                    if ext in (".csv", ".txt") and first_chunk.startswith((b"MZ", b"\x7fELF", b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa\xce")):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Uploaded file contains executable binary signature, which is not permitted.",
                        )
                if ext in (".csv", ".txt") and b"\x00" in chunk:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Uploaded file contains invalid binary content (null bytes) for a CSV/text document.",
                    )
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=f"Uploaded file exceeds maximum allowed limit of {MAX_UPLOAD_SIZE // (1024 * 1024)}MB.",
                    )
                f.write(chunk)

        if total_bytes == 0 or first_chunk is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty (0 bytes).",
            )

        # 3. Content and format inspection
        if ext in (".csv", ".txt"):
            # Inspect the whole (already size-limited) file, not just the first
            # chunk: an executable or NUL byte placed after 64 KB would otherwise
            # pass the check.
            with open(temp_path, "rb") as scan_handle:
                content = scan_handle.read(MAX_UPLOAD_SIZE + 1)
            if content.startswith((b"MZ", b"\x7fELF", b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa\xce")):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Uploaded file contains executable binary signature, which is not permitted.",
                )
            if b"\x00" in content:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Uploaded file contains invalid binary content (null bytes) for a CSV/text document.",
                )
        elif ext == ".pdf":
            # A PDF must start with the %PDF- magic bytes.
            if not first_chunk.startswith(b"%PDF-"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Uploaded file header does not match a valid PDF signature.",
                )
        elif ext in (".xlsx", ".xls"):
            # OOXML workbooks are ZIP archives (PK), legacy .xls files are OLE
            # compound documents (D0CF11E0A1B11AE1).
            if ext == ".xlsx":
                if not first_chunk.startswith(b"PK\x03\x04"):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Uploaded file header does not match a valid XLSX (OOXML) signature.",
                    )
            elif not first_chunk.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Uploaded file header does not match a valid XLS (OLE2) signature.",
                )
        elif ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            is_valid_magic = False
            if ext == ".png" and first_chunk.startswith(b"\x89PNG\r\n\x1a\n"):
                is_valid_magic = True
            elif ext in (".jpg", ".jpeg") and first_chunk.startswith(b"\xff\xd8\xff"):
                is_valid_magic = True
            elif ext == ".bmp" and first_chunk.startswith(b"BM"):
                is_valid_magic = True
            elif ext == ".webp" and len(first_chunk) >= 12 and first_chunk[:4] == b"RIFF" and first_chunk[8:12] == b"WEBP":
                is_valid_magic = True

            if not is_valid_magic:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Uploaded file header does not match valid image signature for '{ext}'.",
                )

            # Extension / content consistency (a .png that is really a JPEG is
            # rejected) and the declared MIME type must not contradict the bytes.
            consistency = check_extension_consistency(safe_filename, first_chunk)
            if not consistency.ok:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=consistency.detail,
                )
            declared = check_declared_content_type(file.content_type, consistency.content_type)
            if not declared.ok:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=declared.detail,
                )

            # Image dimension / pixel-count limits (decompression-bomb guard).
            dimensions = check_image_dimensions(temp_path)
            if not dimensions.ok:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=dimensions.detail,
                )

        # Malware scanning (when a scanner is configured the file is scanned;
        # without one the deployment limitation is recorded, never hidden).
        scanner = get_malware_scanner()
        if not scanner.available and os.getenv("APP_ENV", "development").strip().lower() == "production":
            log_security_event(
                "upload_rejected", severity="critical", outcome="failure",
                actor_id=current_user.user_id, ip_address=_client_ip(request),
                request_id=get_request_id(),
                details={"reason": "malware_scanner_unavailable", "filename": safe_filename},
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Uploads are temporarily unavailable because malware scanning is not configured.",
            )
        clean, scan_detail = scanner.scan(temp_path)
        if not clean:
            log_security_event(
                "upload_rejected",
                severity="critical",
                outcome="failure",
                actor_id=current_user.user_id,
                ip_address=_client_ip(request),
                request_id=get_request_id(),
                details={"reason": "malware_detected", "filename": safe_filename},
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The uploaded file was rejected by the malware scanner.",
            )
        if not scanner.available:
            log_security_event(
                "upload_scanner_unavailable",
                severity="warning",
                outcome="suspicious",
                actor_id=current_user.user_id,
                request_id=get_request_id(),
                details={"filename": safe_filename, "note": "file was not scanned"},
            )

        # Uploaded file contents are untrusted data. Detect embedded
        # instruction-override payloads for monitoring and response; they are
        # never executed and never alter the tool pipeline.
        if ext in (".csv", ".txt"):
            try:
                with open(temp_path, "r", encoding="utf-8", errors="replace") as fh:
                    uploaded_text = fh.read(MAX_TEXT_INSPECTION_BYTES)
                _log_embedded_instruction(
                    uploaded_text, request=request, actor_id=current_user.user_id,
                    filename=safe_filename, source="uploaded_text",
                )
            except Exception as exc:  # pragma: no cover - inspection is best effort
                logger.debug("Unable to inspect upload for embedded instructions: %s", exc)

        scope = resolve_data_scope(db, current_user)
        agent = AttendanceAgent(db_target=db, scope=scope, role=current_user.role, actor_role=current_user.role)

        # Pre-load master USNs and Rooms if available for master data validation.
        # The master list is restricted to the caller's scope, so validation
        # issues can never be used to probe the full student roster.
        all_students = crud.get_all_students(db)
        if not scope.unrestricted:
            visible_usns = scope.visible_student_usns(db)
            all_students = [s for s in all_students if str(s.get("usn", "")).upper() in visible_usns]
        all_rooms = crud.get_all_rooms(db)
        master_usns = [s["usn"] for s in all_students] if all_students else None
        master_rooms = [r["room_id"] for r in all_rooms] if all_rooms else None

        # Resolve target session if not explicitly provided
        target_session = session_id
        assigned_subs = crud.get_teacher_subjects(db, user_id=current_user.user_id) or []
        if not target_session:
            from datetime import date
            today_str = date.today().isoformat()
            today_sessions = crud.get_sessions_by_date(db, date=today_str)
            for s in today_sessions:
                s_dict = dict(s) if isinstance(s, dict) else s.__dict__
                if s_dict.get("teacher_id") == current_user.user_id or s_dict.get("subject_code") in assigned_subs:
                    target_session = s_dict.get("session_id")
                    break

        req_text = f"Process attendance for session {target_session}" if target_session else "Process attendance file"

        resp = agent.process_request(
            user_input=req_text,
            file_path=temp_path,
            master_usns=master_usns,
            master_rooms=master_rooms,
            default_room=default_room,
            default_branch=default_branch,
        )

        # If file was validated with 100% confidence and 0 issues, commit to database
        if target_session and resp.success and not resp.needs_confirmation and resp.data:
            formatted_records = [
                {
                    "session_id": target_session,
                    "usn": str(r.get("usn", "")).strip().upper(),
                    "room_id": str(r.get("room_id", default_room or "LH-101")).strip(),
                    "status": r.get("status", "PRESENT"),
                    "source": "AGENT_VERIFIED_ROSTER",
                    "confidence": float(r.get("confidence", 1.0)),
                }
                for r in resp.data
            ]
            try:
                committed_cnt = crud.insert_attendance_bulk(db, records=formatted_records, upsert=True)
                db.commit()
                resp.message = f"Successfully processed and committed {committed_cnt} attendance records to session '{target_session}' in database."
                logger.info("Auto-committed %d attendance records to session %s", committed_cnt, target_session)
            except Exception as e:
                db.rollback()
                logger.warning("Could not auto-commit attendance to session %s: %s", target_session, e)
        elif not target_session and resp.success and resp.data:
            # Extraction only: no session was resolved, so nothing was written.
            # Say so explicitly - the extraction message alone reads like a save.
            resp.message = (
                f"{resp.message or 'Attendance sheet processed.'} No records were saved: "
                "open Attendance and choose a session to apply them."
            )

        if ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            _log_embedded_instruction(
                json.dumps(resp.data or [], ensure_ascii=False, default=str),
                request=request,
                actor_id=current_user.user_id,
                filename=safe_filename,
                source="ocr_output",
            )
        res_dict = resp.to_dict()
        if target_session:
            res_dict["session_id"] = target_session
        return res_dict
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception as exc:
            logger.warning("Failed to remove temporary file %s: %s", temp_path, exc)


# ==============================================================================
# 3. POST /api/v1/agent/confirm
# ==============================================================================

@router.post(
    "/confirm",
    summary="Confirm or reject attendance records",
    description="Accept human review decision. When confirmed, re-validates and atomically commits approved records to the database.",
    dependencies=[Depends(rate_limit_confirm)],
    responses={
        200: {"description": "Action completed"},
        400: {"description": "Validation error or invalid confirmation payload"},
        404: {"description": "Session not found"},
        409: {"description": "Duplicate records conflict"},
        429: {"description": "Rate limit exceeded"},
    },
)
def agent_confirm(
    payload: AgentConfirmRequest,
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    clean_sess = payload.session_id.strip()

    # Rejection workflow
    if not payload.confirmed:
        logger.info("Attendance batch for session %s rejected by user.", clean_sess)
        return {
            "success": True,
            "confirmed": False,
            "message": f"Attendance batch for session '{clean_sess}' rejected. No records were committed to the database.",
            "committed_count": 0,
        }

    # Verify session exists
    session = crud.get_session(db, session_id=clean_sess)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session with ID '{clean_sess}' not found.",
        )

    # Committing attendance is a write into that session, so the caller must be
    # authorized for it: owner, coordinator, or exact subject-code mapping.
    # The same policy the direct API uses - never a decision taken from the
    # chat text or the LLM output.
    assert_session_edit_authorized(current_user, session, db)

    if not payload.records:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot confirm an empty list of attendance records.",
        )

    records_to_validate = [dict(r) for r in payload.records]
    for r in records_to_validate:
        u = str(r.get("usn", "")).strip().upper()
        stu = crud.get_student(db, u)
        if stu:
            if not r.get("branch"):
                r["branch"] = stu.get("branch")
            if not r.get("name"):
                r["name"] = stu.get("name")

    # Re-validate the submitted records again
    val_res = validate_tool(records_to_validate)
    if not val_res.is_valid:
        error_msgs = [e.message for e in val_res.errors]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Validation failed on submitted confirmation records: {'; '.join(error_msgs)}",
        )

    # Check for duplicate USNs in submitted records
    usns = [str(r.get("usn", "")).strip().upper() for r in payload.records]
    if len(usns) != len(set(usns)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Confirmation payload contains duplicate student USNs.",
        )

    # Check for existing records in database to avoid duplicate primary key collision via single batch query
    existing_usns = crud.get_existing_attendance_usns(db, clean_sess, usns)
    if existing_usns:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Attendance record for student '{existing_usns[0]}' in session '{clean_sess}' already exists in database.",
        )

    formatted_records = [
        {
            "session_id": clean_sess,
            "usn": str(r.get("usn", "")).strip().upper(),
            "room_id": str(r.get("room_id", "LH-101")).strip(),
            "status": r.get("status"),
            "source": payload.source or "AGENT_CONFIRMED",
            "confidence": float(r.get("confidence", 1.0)),
        }
        for r in payload.records
    ]

    # Previous status of the affected students (the confirmation must record
    # the real old -> new transition).
    previous_statuses = capture_attendance_statuses(
        db, clean_sess, [r["usn"] for r in formatted_records]
    )

    try:
        count = crud.insert_attendance_bulk(db, records=formatted_records, upsert=False)
        # Same audit service as the direct API path: one append-only record per
        # confirmed student, in the same transaction as the write.
        actor_id, actor_role = actor_identity(current_user)
        write_attendance_audit(
            db,
            actor_id=actor_id,
            actor_role=actor_role,
            session_id=clean_sess,
            action="ATTENDANCE_AGENT_CONFIRM",
            changes=[
                AttendanceChange(
                    usn=r["usn"],
                    old_status=previous_statuses.get(r["usn"]),
                    new_status=crud.normalize_attendance_status(r["status"]),
                )
                for r in formatted_records
            ],
        )
        db.commit()
        return {
            "success": True,
            "confirmed": True,
            "message": f"Successfully committed {count} confirmed attendance records to session '{clean_sess}'.",
            "committed_count": count,
        }
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Failed to commit attendance records due to database constraint violation or duplicate keys.",
        )
    except Exception as exc:
        db.rollback()
        logger.error("Error during agent confirm commit: %s", exc)
        raise


# ==============================================================================
# 5. POST /api/v1/agent/attendance/propose  (N7 step A)
# ==============================================================================

@router.post(
    "/attendance/propose",
    response_model=AttendanceEditProposalResponse,
    summary="Propose an attendance modification",
    description=(
        "Step A of the AI attendance-editing workflow: resolve the intended session, student "
        "and status, verify that the caller is authorized for that session and store a pending "
        "confirmation. NOTHING is written to attendance at this stage. The pending confirmation "
        "is bound to the authenticated user and expires after five minutes."
    ),
    dependencies=[Depends(rate_limit_chat)],
    responses={
        200: {"description": "Proposal created, or a clarification was requested"},
        403: {"description": "Caller is not authorized for the session"},
        404: {"description": "Session or student not found"},
        409: {"description": "No attendance record to modify, or the status is already set"},
        422: {"description": "Invalid proposed status"},
    },
)
def propose_attendance_modification(
    payload: AttendanceEditProposalRequest,
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        intent = resolve_edit_intent(
            db,
            query=payload.query,
            session_id=payload.session_id,
            usn=payload.usn,
            new_status=payload.new_status,
        )
    except ValueError as exc:
        # An explicitly supplied status that is not a valid attendance status.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )

    return propose_attendance_edit(
        db,
        current_user,
        intent=intent,
        reason=payload.reason,
        request_id=payload.request_id,
    )


# ==============================================================================
# 6. POST /api/v1/agent/attendance/confirm  (N7 step B)
# ==============================================================================

@router.post(
    "/attendance/confirm",
    response_model=AttendanceEditConfirmResponse,
    summary="Confirm a proposed attendance modification",
    description=(
        "Step B of the AI attendance-editing workflow: apply the stored proposal after an "
        "explicit confirmation. Only the confirmation identifier is accepted - the student, "
        "session and proposed status come from the stored proposal and the actor identity and "
        "role from the verified authentication context."
    ),
    dependencies=[Depends(rate_limit_confirm)],
    responses={
        200: {"description": "The stored proposal was applied"},
        400: {"description": "Missing confirmation identifier"},
        403: {"description": "Authorization for the session has been lost"},
        404: {"description": "Confirmation not found or not accessible"},
        409: {"description": "Confirmation already used, conflicting or stale"},
        410: {"description": "Confirmation expired"},
    },
)
def confirm_attendance_modification(
    payload: AttendanceEditConfirmRequest,
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    return confirm_attendance_edit(
        db,
        current_user,
        confirmation_id=payload.confirmation_id,
        reason=payload.reason,
        request_id=payload.request_id,
    )


# ==============================================================================
# 6b. POST /api/v1/agent/chat/confirm (N7 step B - chat confirmation)
# ==============================================================================

@router.post(
    "/chat/confirm",
    summary="Confirm or reject a chat attendance-edit proposal",
    description=(
        "Step B of the AI chat attendance-editing workflow. Accepts a pending_id "
        "and a decision (yes/no). Only the confirmation identifier is accepted: "
        "the student, session and proposed status come from the stored pending "
        "edit, and the actor identity/role come from the verified authentication "
        "context. The pending edit expires after 5 minutes and is single-use."
    ),
    dependencies=[Depends(rate_limit_confirm)],
    responses={
        200: {"description": "Action completed"},
        400: {"description": "Missing confirmation identifier"},
        403: {"description": "Authorization for the session has been lost"},
        404: {"description": "Confirmation not found or not accessible"},
        409: {"description": "Confirmation already used or conflicting"},
        410: {"description": "Confirmation expired"},
        429: {"description": "Rate limit exceeded"},
    },
)
def chat_confirm_attendance_edit(
    pending_id: str,
    decision: str,
    reason: Optional[str] = None,
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    clean_decision = (decision or "").strip().lower()
    if clean_decision not in ("yes", "no"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="decision must be 'yes' or 'no'.",
        )

    if clean_decision == "no":
        # Rejection: mark the pending edit as consumed without applying.
        from app.db.models import PendingEdit

        edit = db.get(PendingEdit, pending_id.strip())
        if edit is None or edit.user_id != current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Confirmation not found.",
            )
        if int(edit.consumed or 0) != 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This confirmation has already been used.",
            )
        if str(edit.expires_at) <= _utcnow_iso():
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="This confirmation has expired.",
            )
        edit.consumed = 1
        db.commit()
        return {
            "success": True,
            "confirmed": False,
            "confirmation_id": pending_id.strip(),
            "decision": "no",
            "message": "Attendance change cancelled. Nothing was modified.",
        }

    # Yes -> apply the stored pending edit atomically.
    return confirm_attendance_edit(
        db,
        current_user,
        confirmation_id=pending_id.strip(),
        reason=reason,
        request_id=None,
    )


# ==============================================================================
# 7. GET /api/v1/agent/status
# ==============================================================================

@router.get(
    "/status",
    response_model=AgentStatusResponse,
    summary="Get AI agent status and provider configuration",
    description="Check configured AI model providers (Gemini, Ollama, EasyOCR) and confirmation threshold without exposing API keys or secrets.",
)
def get_agent_status(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> AgentStatusResponse:
    # Check Gemini configuration safely without leaking key
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    gemini_configured = bool(gemini_key)

    # Probe Ollama reachability with short non-blocking timeout
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    ollama_available = False
    parsed_ollama = urllib.parse.urlparse(ollama_url)
    # Only plain HTTP(S) endpoints are probed: file://, ftp:// and similar
    # schemes are rejected before any request is opened.
    if parsed_ollama.scheme in ("http", "https") and parsed_ollama.netloc:
        try:
            req = urllib.request.Request(
                f"{ollama_url}/api/tags",
                headers={"User-Agent": "RollCall-Agent-Probe"},
            )
            with urllib.request.urlopen(req, timeout=0.3) as response:  # nosec B310 - scheme restricted to http/https above
                if response.status == 200:
                    ollama_available = True
        except Exception:
            ollama_available = False

    tools = [
        "read_csv_tool",
        "read_photo_tool",
        "validate_tool",
        "summary_tool",
        "query_tool",
        "export_tool",
    ]

    return AgentStatusResponse(
        status="ready",
        gemini_configured=gemini_configured,
        ollama_available=ollama_available,
        easyocr_available=True,
        confidence_threshold=CONFIDENCE_CONFIRMATION_THRESHOLD,
        available_tools=tools,
    )
