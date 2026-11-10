"""FastAPI router for AI AttendanceAgent and tool integration."""

from __future__ import annotations

import logging
import os
import tempfile
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
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
from app.auth.session_scope import resolve_session_scope
from app.dependencies import get_db
from app.schemas.agent import (
    AgentConfirmRequest,
    AgentResponseSchema,
    AgentStatusResponse,
    ChatQueryRequest,
)
from app.schemas.auth import AuthenticatedUser
from tools.query_tool import validate_read_only_sql
from tools.validate_tool import validate_tool

logger = logging.getLogger("rollcall.routers.agent")

router = APIRouter(prefix="/agent", tags=["Agent"])

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB limit
ALLOWED_EXTENSIONS = {".csv", ".txt", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}


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

    # Check for raw SQL attempts that violate read-only rules
    if any(k in query_text.lower() for k in ["insert ", "update ", "delete ", "drop ", "alter ", "create ", "replace "]):
        try:
            validate_read_only_sql(query_text)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

    agent = AttendanceAgent(db_target=db)
    req_id = str(uuid.uuid4())

    contextual_query = query_text
    if payload.session_id and f"session {payload.session_id}" not in query_text.lower():
        contextual_query = f"{query_text} for session {payload.session_id}"

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
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    default_room: Optional[str] = Form(None),
    default_branch: Optional[str] = Form(None),
    current_user: AuthenticatedUser = Depends(require_roles(Role.FACULTY)),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
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
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
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
            if first_chunk.startswith((b"MZ", b"\x7fELF", b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa\xce")):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Uploaded file contains executable binary signature, which is not permitted.",
                )
            if b"\x00" in first_chunk:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Uploaded file contains invalid binary content (null bytes) for a CSV/text document.",
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

        agent = AttendanceAgent(db_target=db)

        # Pre-load master USNs and Rooms if available for master data validation
        all_students = crud.get_all_students(db)
        all_rooms = crud.get_all_rooms(db)
        master_usns = [s["usn"] for s in all_students] if all_students else None
        master_rooms = [r["room_id"] for r in all_rooms] if all_rooms else None

        req_text = f"Process attendance for session {session_id}" if session_id else "Process attendance file"

        resp = agent.process_request(
            user_input=req_text,
            file_path=temp_path,
            master_usns=master_usns,
            master_rooms=master_rooms,
            default_room=default_room,
            default_branch=default_branch,
        )
        return resp.to_dict()
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
    scope = resolve_session_scope(db, current_user)
    scope.assert_allowed(session)

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

    try:
        count = crud.insert_attendance_bulk(db, records=formatted_records, upsert=False)
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
# 4. GET /api/v1/agent/status
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
    try:
        req = urllib.request.Request(f"{ollama_url}/api/tags", headers={"User-Agent": "RollCall-Agent-Probe"})
        with urllib.request.urlopen(req, timeout=0.3) as response:
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
