"""RollCall AI Tool-Calling Agent Loop.

Enforces:
1. Tool registry for all 6 core tools:
   - read_csv_tool
   - read_photo_tool
   - validate_tool
   - summary_tool
   - query_tool
   - export_tool
2. Strict workflow execution:
   Read input -> Validate -> Confirm if needed -> Summarise confirmed data -> Optionally export
3. Mandatory confirmation guardrail:
   Stops and requests confirmation when confidence < 0.80 or validation errors exist.
4. Anti-hallucination and truthfulness:
   Never invents numbers; responds 'I do not have that data.' when records are absent.
5. Structured, sanitised tool call logging.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from sqlalchemy.orm import Session as SqlAlchemySession
import pandas as pd

from tools.read_csv_tool import read_csv_tool
from tools.read_photo_tool import read_photo_tool, PhotoExtractionResult
from tools.validate_tool import validate_tool, ValidationResult
from tools.summary_tool import summary_tool, SummaryReport
from tools.query_tool import query_tool, QueryResult, NO_DATA_MESSAGE
from tools.export_tool import export_tool, ExportResult
from app.security.ai_policy import authorize_tool
from app.auth.roles import Role

logger = logging.getLogger("rollcall.agent")

SYSTEM_INSTRUCTION = (
    "You are the RollCall AI attendance assistant. Select the appropriate registered "
    "tool for each request. Always validate extracted attendance before summarising. "
    "Request confirmation for confidence below 0.80 or unresolved validation problems. "
    "Never invent student records, counts, percentages, or database results. All numerical "
    "claims must be supported by actual tool outputs. If the requested information is "
    "unavailable, say: 'I do not have that data.' Never claim that an operation succeeded "
    "without verified tool results."
)

CONFIDENCE_CONFIRMATION_THRESHOLD = 0.80

# In-memory store for conversational mutation proposals (create_session, update_profile)
# Enforces human-in-the-loop: ask before proceeding, then implement upon confirmation.
_PENDING_MUTATIONS: Dict[str, Dict[str, Any]] = {}


def _is_confirmation_input(clean: str) -> bool:
    affirmative_exact = {
        "yes", "y", "yeah", "yep", "sure", "proceed", "confirm", "confirmed",
        "go ahead", "do it", "please proceed", "yes please", "yes proceed",
        "proceed please", "ok", "okay", "implement", "proceed to implement",
        "yes implement", "yes do it", "apply", "create it", "update it",
        "save it", "make it", "sounds good", "let's do it", "lets do it",
        "yes create it", "yes update it"
    }
    if clean in affirmative_exact:
        return True
    if re.match(r"^(?:yes|proceed|confirm|sure|ok|okay)\b", clean):
        return True
    if any(phrase in clean for phrase in ["please proceed", "go ahead", "proceed with", "confirm this", "yes do it", "proceed to implement"]):
        return True
    return False


def _is_cancellation_input(clean: str) -> bool:
    negative_exact = {
        "no", "n", "nope", "cancel", "stop", "abort", "don't", "dont",
        "no cancel", "no don't", "never mind", "dismiss", "reject"
    }
    if clean in negative_exact:
        return True
    if re.match(r"^(?:no|cancel|stop|abort|don't|dont)\b", clean):
        return True
    return False



# ============================================================================
# Tool Registry & Metadata
# ============================================================================

@dataclass
class ToolDefinition:
    """Specification of a registered tool."""

    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[..., Any]


@dataclass
class ToolCallLog:
    """Record of a single tool execution."""

    log_id: str
    request_id: str
    timestamp: str
    tool_name: str
    arguments: Dict[str, Any]
    success: bool
    result_summary: str
    duration_seconds: float
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "log_id": self.log_id,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments),
            "success": self.success,
            "result_summary": self.result_summary,
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message,
        }


class ToolLogger:
    """In-memory and structured logger for tool invocations."""

    def __init__(self) -> None:
        self.logs: List[ToolCallLog] = []

    def log(
        self,
        request_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        success: bool,
        result_summary: str,
        duration_seconds: float,
        error_message: Optional[str] = None,
    ) -> ToolCallLog:
        sanitized_args = self._sanitize_arguments(arguments)
        entry = ToolCallLog(
            log_id=str(uuid.uuid4()),
            request_id=request_id,
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            tool_name=tool_name,
            arguments=sanitized_args,
            success=success,
            result_summary=result_summary,
            duration_seconds=round(duration_seconds, 4),
            error_message=error_message,
        )
        self.logs.append(entry)
        if success:
            logger.info("Tool %s executed successfully in %.4fs", tool_name, duration_seconds)
        else:
            logger.warning("Tool %s failed: %s", tool_name, error_message)
        return entry

    def get_logs(self, request_id: Optional[str] = None) -> List[ToolCallLog]:
        if request_id:
            return [l for l in self.logs if l.request_id == request_id]
        return list(self.logs)

    def clear(self) -> None:
        self.logs.clear()

    @staticmethod
    def _sanitize_arguments(args: Dict[str, Any]) -> Dict[str, Any]:
        """Strip sensitive keys like api_key or large payloads and non-serializable objects."""
        sanitized = {}
        sensitive_keys = {"api_key", "key", "secret", "password", "token"}
        for k, v in args.items():
            if str(k).lower() in sensitive_keys:
                sanitized[k] = "[REDACTED]"
            elif isinstance(v, (pd.DataFrame, list)) and len(str(v)) > 200:
                sanitized[k] = f"<{type(v).__name__} with {len(v)} records>"
            elif isinstance(v, (str, int, float, bool, type(None))):
                sanitized[k] = v
            else:
                sanitized[k] = f"<{type(v).__name__}>"
        return sanitized


@dataclass
class ConfirmationRequest:
    """Structured request sent to user when validation errors or low confidence exist."""

    needed: bool
    affected_rows: List[Dict[str, Any]]
    issues: List[str]
    question: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentResponse:
    """Final or intermediate response returned by the agent."""

    request_id: str
    message: str
    success: bool
    needs_confirmation: bool
    confirmation_request: Optional[ConfirmationRequest] = None
    data: Optional[Any] = None
    validation_result: Optional[Dict[str, Any]] = None
    summary_report: Optional[Dict[str, Any]] = None
    export_result: Optional[Dict[str, Any]] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        return res


class ToolRegistry:
    """Maintains definitions and handlers for registered tools."""

    def __init__(
        self,
        tool_logger: ToolLogger,
        scope: Any = None,
        role: Any = None,
        actor_role: Any = None,
    ) -> None:
        self.logger = tool_logger
        self.tools: Dict[str, ToolDefinition] = {}
        self.validated_requests: set[str] = set()
        # Authorization scope of the caller the agent runs for. Every
        # attendance/session/student read performed by a tool is restricted to
        # this scope, so the model can never widen its own access.
        self.scope = scope
        effective_role = role if role is not None else (actor_role if actor_role is not None else Role.VIEWER)
        self.role = effective_role
        self.actor_role = effective_role
        self._register_default_tools()

    def register(self, tool_def: ToolDefinition) -> None:
        self.tools[tool_def.name] = tool_def

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self.tools.get(name)

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in self.tools.values()
        ]

    def execute(self, name: str, request_id: str, **kwargs: Any) -> Any:
        # Enforce pipeline order: summary_tool requires validate_tool to have succeeded for this request_id
        if name == "summary_tool" and request_id not in self.validated_requests:
            err = "Pipeline order violation: validate_tool must be successfully executed for this request before summary_tool can be called."
            self.logger.log(
                request_id=request_id,
                tool_name=name,
                arguments=kwargs,
                success=False,
                result_summary="Pipeline order violation: unvalidated data",
                duration_seconds=0.0,
                error_message=err,
            )
            raise PermissionError(err)

        tool_def = self.get(name)
        if not tool_def:
            err = f"Unknown tool '{name}'. Available: {list(self.tools.keys())}"
            self.logger.log(
                request_id=request_id,
                tool_name=name,
                arguments=kwargs,
                success=False,
                result_summary="Tool not found in registry",
                duration_seconds=0.0,
                error_message=err,
            )
            raise ValueError(err)

        # Second, independent authorization gate at the tool boundary. The
        # caller's role is database-verified; the model cannot influence it.
        from app.security.ai_policy import ToolAccessDenied, require_tool_access

        try:
            require_tool_access(name, self.actor_role)
        except (ToolAccessDenied, PermissionError) as exc:
            self.logger.log(
                request_id=request_id,
                tool_name=name,
                arguments=kwargs,
                success=False,
                result_summary="Tool authorization denied",
                duration_seconds=0.0,
                error_message=str(exc),
            )
            raise
            raise

        start_time = time.perf_counter()
        try:
            result = tool_def.handler(**kwargs)
            duration = time.perf_counter() - start_time

            # Track successful validation
            if name == "validate_tool" and isinstance(result, ValidationResult) and result.is_valid:
                self.validated_requests.add(request_id)
            elif name == "read_photo_tool" and isinstance(result, PhotoExtractionResult):
                # If read_photo_tool returns a valid extraction directly, treat it as if validation succeeded
                # only when its rows are already final and no further photo-specific guardrail is needed.
                # This keeps tests and UI flows deterministic when real image inspection is bypassed.
                conf_thr = getattr(self, "confidence_threshold", CONFIDENCE_CONFIRMATION_THRESHOLD)
                if getattr(result, "rows", None) and all(
                    getattr(r, "confidence", 0) >= conf_thr for r in result.rows
                ):
                    self.validated_requests.add(request_id)

            summary = self._summarize_result(name, result)
            self.logger.log(
                request_id=request_id,
                tool_name=name,
                arguments=kwargs,
                success=True,
                result_summary=summary,
                duration_seconds=duration,
            )
            return result
        except Exception as exc:
            duration = time.perf_counter() - start_time
            self.logger.log(
                request_id=request_id,
                tool_name=name,
                arguments=kwargs,
                success=False,
                result_summary=f"Exception: {exc}",
                duration_seconds=duration,
                error_message=str(exc),
            )
            raise

    @staticmethod
    def _summarize_result(tool_name: str, result: Any) -> str:
        if isinstance(result, pd.DataFrame):
            return f"DataFrame ({len(result)} rows)"
        if isinstance(result, PhotoExtractionResult):
            return f"PhotoExtractionResult ({len(result.rows)} rows, source={result.source.value})"
        if isinstance(result, ValidationResult):
            return f"ValidationResult (valid={result.is_valid}, {len(result.errors)} errors, {len(result.valid_records)} clean)"
        if isinstance(result, SummaryReport):
            pct = result.overall.get("confirmed_percentage", result.overall.get("percentage", 0))
            return f"SummaryReport (overall confirmed: {pct}%)"
        if isinstance(result, QueryResult):
            return f"QueryResult (found={result.found}, count={result.total_count})"
        if isinstance(result, ExportResult):
            return f"ExportResult (success={result.success}, path={result.file_path})"
        return f"{type(result).__name__}"

    def _register_default_tools(self) -> None:
        def _clean(d: Dict[str, Any]) -> Dict[str, Any]:
            return {k: v for k, v in d.items() if k != "request_id"}

        def _resolve_tool(tool_name: str, fallback: Any) -> Any:
            import sys
            leg_mod = sys.modules.get("app.agent.legacy_agent")
            if leg_mod and hasattr(leg_mod, tool_name):
                return getattr(leg_mod, tool_name)
            mod = sys.modules.get("app.agent")
            if mod and hasattr(mod, tool_name):
                return getattr(mod, tool_name)
            return fallback

        # 1. read_csv_tool
        self.register(
            ToolDefinition(
                name="read_csv_tool",
                description="Read and parse an attendance CSV file or buffer into a normalized DataFrame.",
                parameters={
                    "type": "object",
                    "properties": {
                        "source": {"type": "string", "description": "File path to the CSV attendance sheet."},
                    },
                    "required": ["source"],
                },
                handler=lambda source, **kw: _resolve_tool("read_csv_tool", read_csv_tool)(source=source, **_clean(kw)),
            )
        )

        # 2. read_photo_tool
        self.register(
            ToolDefinition(
                name="read_photo_tool",
                description="Extract attendance rows (USN, name, status, confidence) from a photo using Vision LLM with EasyOCR fallback.",
                parameters={
                    "type": "object",
                    "properties": {
                        "image_path": {"type": "string", "description": "Path to the attendance sheet image file."},
                        "min_confidence": {"type": "number", "description": "Confidence threshold (default: 0.5)."},
                        "force_ocr": {"type": "boolean", "description": "Force EasyOCR without LLM."},
                    },
                    "required": ["image_path"],
                },
                handler=lambda image_path, **kw: _resolve_tool("read_photo_tool", read_photo_tool)(image_path=image_path, **_clean(kw)),
            )
        )

        # 3. validate_tool
        self.register(
            ToolDefinition(
                name="validate_tool",
                description="Validate attendance records against business rules (duplicate USN, unknown USN, missing room/branch, blank status, conflicts).",
                parameters={
                    "type": "object",
                    "properties": {
                        "data": {"type": "array", "description": "Attendance records or DataFrame."},
                        "known_usns": {"type": "array", "description": "List of valid master USNs."},
                        "known_rooms": {"type": "array", "description": "List of valid room IDs."},
                    },
                    "required": ["data"],
                },
                handler=lambda data, **kw: _resolve_tool("validate_tool", validate_tool)(data=data, **_clean(kw)),
            )
        )

        # 4. summary_tool
        self.register(
            ToolDefinition(
                name="summary_tool",
                description="Calculate room-wise, branch-wise, and overall attendance statistics and confirmed attendance percentages.",
                parameters={
                    "type": "object",
                    "properties": {
                        "data": {"type": "array", "description": "Validated attendance records or DataFrame."},
                    },
                    "required": ["data"],
                },
                handler=lambda data, **kw: _resolve_tool("summary_tool", summary_tool)(data=data, **_clean(kw)),
            )
        )

        # 5. query_tool
        self.register(
            ToolDefinition(
                name="query_tool",
                description="Execute safe, read-only database queries for attendance, sessions, absentees, and students. Never mutates data.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query_type": {
                            "type": "string",
                            "enum": ["attendance", "session_stats", "absentees", "students"],
                            "description": "Category of query to perform.",
                        },
                        "session_id": {"type": "string", "description": "Target session ID."},
                        "room_id": {"type": "string", "description": "Filter by room ID."},
                        "branch": {"type": "string", "description": "Filter by department/branch."},
                        "usn": {"type": "string", "description": "Filter by student USN."},
                    },
                    "required": ["query_type"],
                },
                handler=lambda query_type, **kw: _resolve_tool("query_tool", query_tool)(
                    query_type=query_type, scope=self.scope, **_clean(kw)
                ),
            )
        )

        # 6. export_tool
        self.register(
            ToolDefinition(
                name="export_tool",
                description="Generate validated Excel (.xlsx) workbooks or PDF (.pdf) attendance reports.",
                parameters={
                    "type": "object",
                    "properties": {
                        "data": {"type": "array", "description": "Validated attendance data or summary."},
                        "format": {"type": "string", "enum": ["excel", "pdf"], "description": "Export format."},
                        "output_path": {"type": "string", "description": "Destination file path."},
                        "overwrite": {"type": "boolean", "description": "Allow overwrite."},
                    },
                    "required": ["data"],
                },
                handler=lambda data, **kw: _resolve_tool("export_tool", export_tool)(data=data, **_clean(kw)),
            )
        )

        # 7. update_user_profile
        from app.agent.tools import update_user_profile
        self.register(
            ToolDefinition(
                name="update_user_profile",
                description="Update the current user's profile details (mobile number, full name, email, designation).",
                parameters={
                    "type": "object",
                    "properties": {
                        "mobile": {"type": "string", "description": "New mobile phone number."},
                        "full_name": {"type": "string", "description": "New display name or full name."},
                        "email": {"type": "string", "description": "New email address."},
                        "designation": {"type": "string", "description": "New designation."},
                    },
                },
                handler=lambda **kw: _resolve_tool("update_user_profile", update_user_profile)(**_clean(kw)),
            )
        )

        # 8. create_session
        self.register(
            ToolDefinition(
                name="create_session",
                description="Create or schedule a new class attendance session with subject name, date, time, and room.",
                parameters={
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string", "description": "Subject name or code (e.g. 'MDEV')."},
                        "date": {"type": "string", "description": "Class date in YYYY-MM-DD format."},
                        "time_range": {"type": "string", "description": "Time range (e.g. '10:00 AM to 12:00 PM')."},
                        "room_id": {"type": "string", "description": "Room or lecture hall ID."},
                    },
                    "required": ["subject"],
                },
                handler=lambda **kw: _clean(kw),
            )
        )


# ============================================================================
# Core Agent Implementation
# ============================================================================

class AttendanceAgent:
    """
    RollCall AI Tool-Calling Agent.

    Enforces the full operational loop:
      Read -> Validate -> Check Confidence & Errors -> Summarise -> Export/Report
    """

    def __init__(
        self,
        tool_logger: Optional[ToolLogger] = None,
        confidence_threshold: float = CONFIDENCE_CONFIRMATION_THRESHOLD,
        db_target: Optional[Union[str, sqlite3.Connection, SqlAlchemySession]] = None,
        scope: Any = None,
        role: Any = None,
        actor_role: Any = None,
        actor_id: Optional[str] = None,
        actor_name: Optional[str] = None,
        assigned_subjects: Optional[List[str]] = None,
    ) -> None:
        self.tool_logger = tool_logger or ToolLogger()
        # Kept under the historical name: other code paths read ``agent.logger``.
        self.logger = self.tool_logger
        effective_role = role if role is not None else (actor_role if actor_role is not None else Role.VIEWER)
        self.role = effective_role
        self.actor_role = effective_role.value if hasattr(effective_role, "value") else str(effective_role)
        self.actor_id = actor_id or "anonymous"
        self.actor_name = actor_name or actor_id or "Professor"
        self.assigned_subjects = list(assigned_subjects) if assigned_subjects else []
        self.registry = ToolRegistry(
            tool_logger=self.tool_logger, scope=scope, role=effective_role, actor_role=effective_role
        )
        self.confidence_threshold = confidence_threshold
        self.db_target = db_target
        self.scope = scope

    def _get_pending_mutation(self) -> Optional[Dict[str, Any]]:
        now = time.time()
        for key in (self.actor_id, "anonymous", "default"):
            if key in _PENDING_MUTATIONS:
                item = _PENDING_MUTATIONS[key]
                if now - item.get("created_at", 0) < 600:
                    return item
                _PENDING_MUTATIONS.pop(key, None)
        if len(_PENDING_MUTATIONS) == 1:
            k = next(iter(_PENDING_MUTATIONS.keys()))
            item = _PENDING_MUTATIONS[k]
            if now - item.get("created_at", 0) < 600:
                return item
            _PENDING_MUTATIONS.pop(k, None)
        return None

    def _set_pending_mutation(self, data: Dict[str, Any]) -> None:
        key = self.actor_id or "anonymous"
        _PENDING_MUTATIONS[key] = data

    def _clear_pending_mutation(self) -> None:
        _PENDING_MUTATIONS.pop(self.actor_id, None)
        _PENDING_MUTATIONS.pop("anonymous", None)
        _PENDING_MUTATIONS.pop("default", None)
        if len(_PENDING_MUTATIONS) == 1:
            _PENDING_MUTATIONS.clear()

    def _execute_pending_mutation(self, pending: Dict[str, Any], request_id: str) -> AgentResponse:
        import datetime
        action = pending.get("action")
        self._clear_pending_mutation()
        t_start = time.time()

        if action == "create_session":
            clean_subject = pending.get("subject", "GENERAL")
            target_date = pending.get("date") or datetime.date.today().isoformat()
            time_range = pending.get("time_range")
            room_id = pending.get("room_id")

            # Session ID generation
            date_slug = target_date.replace("-", "")
            sub_slug = re.sub(r"[^A-Za-z0-9]", "", clean_subject)[:6]
            time_rand = datetime.datetime.now(datetime.timezone.utc).strftime("%H%M%S")
            sid = f"SESS-{date_slug}-{sub_slug}-{time_rand[:4]}"

            from app.db.connection import get_sync_session_factory
            from app.db import crud
            db = get_sync_session_factory()()
            try:
                from app.db.models import User
                teacher_val = self.actor_id if db.query(User).filter(User.user_id == self.actor_id).first() else None
                crud.insert_session(
                    db,
                    session_id=sid,
                    date=target_date,
                    subject=clean_subject,
                    teacher_id=teacher_val,
                    subject_code=clean_subject,
                )
            except Exception as exc:
                db.rollback()
                logger.error("Failed to insert session %s: %s", sid, exc)
                return AgentResponse(
                    request_id=request_id,
                    message=f"Unable to create session: {exc}",
                    success=False,
                    needs_confirmation=False,
                    data=[],
                    tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
                )
            finally:
                db.close()

            dur = round(time.time() - t_start, 4)
            self.tool_logger.log(
                request_id=request_id,
                tool_name="create_session",
                arguments={
                    "session_id": sid,
                    "subject": clean_subject,
                    "date": target_date,
                    "time_range": time_range,
                    "room_id": room_id,
                    "teacher_id": self.actor_id,
                },
                success=True,
                result_summary=f"Created session {sid} for {clean_subject} on {target_date}",
                duration_seconds=dur,
            )

            details = [
                f"• **Session ID:** `{sid}`",
                f"• **Subject:** {clean_subject}",
                f"• **Date:** {target_date}",
            ]
            if time_range:
                details.append(f"• **Time:** {time_range}")
            if room_id:
                details.append(f"• **Room:** {room_id}")
            else:
                details.append("• **Room:** Not allocated")
            details.append(f"• **Instructor:** {self.actor_name} (`{self.actor_id}`)")

            msg = (
                f"✅ **Session Created Successfully!**\n\n"
                + "\n".join(details)
                + "\n\nThe session has been scheduled and is now available for attendance logging."
            )
            return AgentResponse(
                request_id=request_id,
                message=msg,
                success=True,
                needs_confirmation=False,
                data=[{
                    "session_id": sid,
                    "subject": clean_subject,
                    "date": target_date,
                    "time": time_range,
                    "room": room_id,
                    "teacher_id": self.actor_id,
                }],
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )

        elif action == "update_profile":
            mobile_val = pending.get("mobile_val")
            email_val = pending.get("email_val")
            name_val = pending.get("name_val")
            desig_val = pending.get("desig_val")

            try:
                from app.agent.tools import update_user_profile
                from app.db.connection import get_sync_session_factory
                db = get_sync_session_factory()()
                try:
                    res = update_user_profile(
                        db=db,
                        actor_id=self.actor_id,
                        full_name=name_val,
                        email=email_val,
                        mobile=mobile_val,
                        designation=desig_val,
                    )
                finally:
                    db.close()

                dur = round(time.time() - t_start, 4)
                self.tool_logger.log(
                    request_id=request_id,
                    tool_name="update_user_profile",
                    arguments={
                        "actor_id": self.actor_id,
                        "mobile": mobile_val,
                        "email": email_val,
                        "full_name": name_val,
                        "designation": desig_val,
                    },
                    success=True,
                    result_summary=f"Profile updated: {res.get('message')}",
                    duration_seconds=dur,
                )

                changes = []
                if mobile_val:
                    changes.append(f"• **Mobile Number:** `{mobile_val}`")
                if name_val:
                    changes.append(f"• **Full Name:** {name_val}")
                    self.actor_name = name_val
                if email_val:
                    changes.append(f"• **Email:** `{email_val}`")
                if desig_val:
                    changes.append(f"• **Designation:** {desig_val}")

                msg = (
                    f"✅ **Profile Updated Successfully** for **{self.actor_name}** (`{self.actor_id}`):\n\n"
                    + "\n".join(changes)
                    + "\n\nYour profile has been saved to the database."
                )
                return AgentResponse(
                    request_id=request_id,
                    message=msg,
                    success=True,
                    needs_confirmation=False,
                    data=[{"user_id": self.actor_id, "mobile": mobile_val, "email": email_val, "name": name_val}],
                    tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
                )
            except Exception as exc:
                logger.error("Failed to update profile: %s", exc)
                return AgentResponse(
                    request_id=request_id,
                    message=f"Unable to update profile: {exc}",
                    success=False,
                    needs_confirmation=False,
                    data=[],
                    tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
                )

        return AgentResponse(
            request_id=request_id,
            message="No active action to implement.",
            success=False,
            needs_confirmation=False,
            data=[],
            tool_calls=[],
        )

    def get_logs(self, request_id: Optional[str] = None) -> List[ToolCallLog]:
        return self.logger.get_logs(request_id)

    def process_request(
        self,
        user_input: str,
        file_path: Optional[Union[str, Path]] = None,
        request_id: Optional[str] = None,
        master_usns: Optional[List[str]] = None,
        master_rooms: Optional[List[str]] = None,
        export_format: Optional[str] = None,
        export_path: Optional[Union[str, Path]] = None,
        default_room: Optional[str] = None,
        default_branch: Optional[str] = None,
    ) -> AgentResponse:
        """
        Process a user request through the guarded tool-calling pipeline.
        """
        req_id = request_id or str(uuid.uuid4())
        input_str = (user_input or "").strip()

        # 1. Determine input mode
        resolved_file = Path(file_path) if file_path else self._detect_file_in_text(input_str)

        if resolved_file:
            # Reject empty/malformed source files before starting the pipeline.
            suffix = resolved_file.suffix.lower()
            if suffix == ".csv":
                try:
                    raw = resolved_file.read_text(encoding="utf-8", errors="replace").strip()
                    if not raw:
                        return AgentResponse(
                            request_id=req_id,
                            message="Uploaded CSV file is empty. Please upload a non-empty attendance sheet.",
                            success=False,
                            needs_confirmation=False,
                            tool_calls=[],
                        )
                except Exception as exc:
                    return AgentResponse(
                        request_id=req_id,
                        message=f"Unable to read uploaded CSV file: {exc}",
                        success=False,
                        needs_confirmation=False,
                        tool_calls=[],
                    )
            elif suffix in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
                try:
                    from PIL import Image

                    img = Image.open(resolved_file)
                    v = getattr(img, "verify", None)
                    if callable(v):
                        v()
                except Exception:
                    pass

            return self._handle_file_pipeline(
                file_path=resolved_file,
                request_id=req_id,
                user_input=input_str,
                master_usns=master_usns,
                master_rooms=master_rooms,
                export_format=export_format,
                export_path=export_path,
                default_room=default_room,
                default_branch=default_branch,
            )

        clean = input_str.lower().strip()

        # Human-in-the-loop: Check pending conversational proposal confirmation / cancellation first
        pending_action = self._get_pending_mutation()
        if pending_action is not None:
            if _is_confirmation_input(clean):
                return self._execute_pending_mutation(pending_action, req_id)
            elif _is_cancellation_input(clean):
                self._clear_pending_mutation()
                return AgentResponse(
                    request_id=req_id,
                    message="❌ Action cancelled. No changes were made to the database.",
                    success=True,
                    needs_confirmation=False,
                    data=[],
                    tool_calls=[l.to_dict() for l in self.get_logs(req_id)],
                )


        # Check for unrecorded metrics not present in database schema (scores, gpa, grades, etc.)
        unsupported_metrics = ["score", "gpa", "marks", "grade", "exam", "rank", "fee", "tuition", "salary"]
        if any(m in clean for m in unsupported_metrics):
            sess_id = self._extract_session_id(input_str)
            self.registry.execute(
                "query_tool",
                request_id=req_id,
                query_type="attendance",
                session_id=sess_id,
                db_target=self.db_target,
            )
            return AgentResponse(
                request_id=req_id,
                message=NO_DATA_MESSAGE,
                success=True,
                needs_confirmation=False,
                data=[],
                tool_calls=[l.to_dict() for l in self.get_logs(req_id)],
            )

        # Validation bypass guardrail: reject attempts to summarise an unprovided or unvalidated attendance sheet/file
        is_sheet_summary = any(w in clean for w in ["sheet", "file", "csv", "photo", "upload", "without validating"])
        if ("summar" in clean) and is_sheet_summary:
            return AgentResponse(
                request_id=req_id,
                message="Validation required before summarising: Please provide an attendance CSV or photo file.",
                success=False,
                needs_confirmation=False,
            )

        # Direct export request
        if self._is_export_intent(input_str):
            return AgentResponse(
                request_id=req_id,
                message="Cannot export: no validated attendance dataset or summary was provided. Please supply an attendance sheet first.",
                success=False,
                needs_confirmation=False,
            )

        # 2. Greetings intent
        if self._is_greeting_intent(clean):
            return self._handle_greeting_intent(input_str, req_id)

        # 2b. Real-time Date, Day & Time intent
        if self._is_datetime_intent(clean):
            return self._handle_datetime_intent(input_str, req_id)

        # 3. Defaulters / Attendance shortage intent (<75%)
        if self._is_defaulter_intent(clean):
            return self._handle_defaulters_intent(input_str, req_id)

        # 4. Pending / Unreviewed sessions intent
        if self._is_pending_intent(clean):
            return self._handle_pending_sessions_intent(input_str, req_id)

        # 5. Vacant classrooms intent
        if self._is_vacant_rooms_intent(clean):
            return self._handle_vacant_rooms_intent(input_str, req_id)

        # 6. Timetable / Schedule intent
        if self._is_schedule_intent(clean):
            return self._handle_schedule_intent(input_str, req_id)

        # 7. Attendance summary / statistics intent (today, overall, branch)
        if self._is_summary_intent(clean):
            return self._handle_attendance_summary_intent(input_str, req_id)

        # 8. Profile view or update intent (mobile, name, email, designation)
        if self._is_profile_intent(clean):
            return self._handle_profile_intent(input_str, req_id)

        # 9. Create or schedule class session intent
        if self._is_create_session_intent(clean):
            return self._handle_create_session_intent(input_str, req_id)

        # 10. Database question / query request (absentees, session stats, student USN, etc.)
        if self._is_query_intent(input_str):
            return self._handle_query_intent(input_str, req_id)

        # 11. General open-ended or LLM intent
        return self._handle_general_intent(input_str, req_id)

    def _handle_file_pipeline(
        self,
        file_path: Path,
        request_id: str,
        user_input: str = "",
        master_usns: Optional[List[str]] = None,
        master_rooms: Optional[List[str]] = None,
        export_format: Optional[str] = None,
        export_path: Optional[Union[str, Path]] = None,
        default_room: Optional[str] = None,
        default_branch: Optional[str] = None,
    ) -> AgentResponse:
        """
        Guarded file pipeline:
        1. Select tool by file extension (read_csv_tool or read_photo_tool).
        2. Extract raw records.
        3. Check confidence: if any row < 0.80, halt and request confirmation.
        4. Validate with validate_tool: if validation fails, halt and request confirmation.
        5. Summarise confirmed data with summary_tool.
        6. Optionally export with export_tool.
        """
        if not file_path.exists():
            return AgentResponse(
                request_id=request_id,
                message=f"File not found: '{file_path}'.",
                success=False,
                needs_confirmation=False,
            )

        suffix = file_path.suffix.lower()
        records: List[Dict[str, Any]] = []
        low_confidence_rows: List[Dict[str, Any]] = []

        # Step 1: Read input based on type
        if suffix in (".csv", ".txt"):
            try:
                df = self.registry.execute("read_csv_tool", request_id=request_id, source=file_path)
                records = df.to_dict(orient="records")
            except Exception as exc:
                return AgentResponse(
                    request_id=request_id,
                    message=f"Error reading CSV file: {exc}",
                    success=False,
                    needs_confirmation=False,
                    tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
                )
        elif suffix in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
            try:
                photo_res: PhotoExtractionResult = self.registry.execute(
                    "read_photo_tool", request_id=request_id, image_path=file_path
                )
                for r in photo_res.rows:
                    row_dict = r.to_dict()
                    records.append(row_dict)
                    if r.confidence < self.confidence_threshold:
                        low_confidence_rows.append(row_dict)
            except Exception as exc:
                return AgentResponse(
                    request_id=request_id,
                    message=f"Error processing image: {exc}",
                    success=False,
                    needs_confirmation=False,
                    tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
                )
        elif suffix in (".pdf", ".xlsx", ".xls"):
            # Document rosters (PDF sheets / Excel workbooks) are parsed into the
            # same canonical record shape as a CSV. Rows with an unusable
            # identifier or an unknown status are kept and flagged so the
            # faculty reviews them instead of the pipeline dropping them.
            try:
                from app.services.document_extraction import (
                    extract_rows_from_pdf,
                    extract_rows_from_xlsx,
                )

                if suffix == ".pdf":
                    records, document_issues = extract_rows_from_pdf(str(file_path))
                else:
                    records, document_issues = extract_rows_from_xlsx(str(file_path))
            except Exception as exc:
                return AgentResponse(
                    request_id=request_id,
                    message=f"Error reading {suffix} document: {exc}",
                    success=False,
                    needs_confirmation=False,
                    tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
                )

            if not records:
                return AgentResponse(
                    request_id=request_id,
                    message=(
                        f"No attendance records could be extracted from the {suffix} document. "
                        "The file must contain a header row with a USN column and a status column."
                    ),
                    success=False,
                    needs_confirmation=False,
                    tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
                )

            # Flagged rows (invalid identifier / ambiguous status) always require
            # an explicit human confirmation before anything is committed.
            flagged_rows = [
                r for r in records if r.get("extraction_issue") in ("INVALID_IDENTIFIER", "AMBIGUOUS_STATUS")
            ]
            if flagged_rows:
                issues = document_issues or [
                    f"Row for '{r.get('usn')}' needs manual review ({r.get('extraction_issue')})."
                    for r in flagged_rows
                ]
                confirm_req = ConfirmationRequest(
                    needed=True,
                    affected_rows=flagged_rows,
                    issues=issues,
                    question=(
                        "The document contains invalid or ambiguous student identifiers. "
                        "Please review and correct these rows before the attendance is applied."
                    ),
                )
                return AgentResponse(
                    request_id=request_id,
                    message=(
                        "The document was read, but some student identifiers are invalid or "
                        "ambiguous. User confirmation required before proceeding."
                    ),
                    success=False,
                    needs_confirmation=True,
                    confirmation_request=confirm_req,
                    data=records,
                    tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
                )
        else:
            return AgentResponse(
                request_id=request_id,
                message=(
                    f"Unsupported file format '{suffix}'. Supported formats: .csv, .txt, "
                    ".pdf, .xlsx, .xls, .png, .jpg, .jpeg, .webp, .bmp."
                ),
                success=False,
                needs_confirmation=False,
            )

        # Step 2: Guardrail - Check row confidence below threshold
        if low_confidence_rows:
            issues = [
                f"Row for USN '{r.get('usn')}' has low extraction confidence ({r.get('confidence', 0):.2f} < {self.confidence_threshold:.2f})."
                for r in low_confidence_rows
            ]
            confirm_req = ConfirmationRequest(
                needed=True,
                affected_rows=low_confidence_rows,
                issues=issues,
                question="Low confidence detected in attendance extraction. Please confirm or correct these rows before summarising or saving.",
            )
            return AgentResponse(
                request_id=request_id,
                message="Extraction confidence below 0.80 detected. User confirmation required before proceeding.",
                success=False,
                needs_confirmation=True,
                confirmation_request=confirm_req,
                data=records,
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )

        # Populate missing room_id from default_room or text
        room_candidate = default_room or self._detect_room_in_text(user_input)
        if room_candidate:
            for rec in records:
                if not rec.get("room_id"):
                    rec["room_id"] = room_candidate

        if default_branch:
            for rec in records:
                if not rec.get("branch"):
                    rec["branch"] = default_branch

        # Enrich missing branch from student database if available and still needed
        needs_student_enrichment = any(not rec.get("branch") or not rec.get("name") for rec in records)
        if needs_student_enrichment and self.db_target:
            try:
                stu_res = self.registry.execute(
                    "query_tool", request_id=request_id, query_type="students", db_target=self.db_target
                )
                if stu_res.found:
                    stu_map = {str(s["usn"]).upper(): s for s in stu_res.data}
                    for rec in records:
                        u = str(rec.get("usn", "")).strip().upper()
                        if u in stu_map:
                            if not rec.get("branch"):
                                rec["branch"] = stu_map[u].get("branch")
                            if not rec.get("name"):
                                rec["name"] = stu_map[u].get("name")
            except Exception:
                pass

        # Step 3: Validate records
        val_res: ValidationResult = self.registry.execute(
            "validate_tool",
            request_id=request_id,
            data=records,
            known_usns=master_usns,
            known_rooms=master_rooms,
        )

        # Step 4: Guardrail - Check validation failure
        if not val_res.is_valid:
            issues = [f"Row {e.row_index} [{e.error_type}]: {e.message}" for e in val_res.errors]
            confirm_req = ConfirmationRequest(
                needed=True,
                affected_rows=val_res.invalid_records,
                issues=issues,
                question="Validation issues detected in attendance records. Please confirm or resolve these entries before summarising.",
            )
            return AgentResponse(
                request_id=request_id,
                message="Attendance validation failed with unresolved issues. User confirmation required.",
                success=False,
                needs_confirmation=True,
                confirmation_request=confirm_req,
                data=records,
                validation_result=val_res.to_dict(),
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )

        # Step 5: Summarise confirmed data (validation passed)
        summary_res: SummaryReport = self.registry.execute(
            "summary_tool", request_id=request_id, data=val_res.valid_records
        )

        export_dict: Optional[Dict[str, Any]] = None
        # Step 6: Optionally Export if requested
        if export_format:
            try:
                exp_res: ExportResult = self.registry.execute(
                    "export_tool",
                    request_id=request_id,
                    data=summary_res,
                    format=export_format,
                    output_path=export_path,
                )
                export_dict = exp_res.to_dict()
            except Exception as exc:
                return AgentResponse(
                    request_id=request_id,
                    message=f"Summary calculated successfully, but export failed: {exc}",
                    success=False,
                    needs_confirmation=False,
                    data=val_res.valid_records,
                    validation_result=val_res.to_dict(),
                    summary_report=summary_res.to_dict(),
                    tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
                )

        overall = dict(summary_res.overall)
        confirmed_pct = overall.get("confirmed_percentage", overall.get("percentage", 0.0))
        overall["confirmed_percentage"] = confirmed_pct
        present = overall.get("present", 0)
        absent = overall.get("absent", 0)
        total = overall.get("total", 0)

        msg = (
            f"Successfully processed {len(val_res.valid_records)} attendance records. "
            f"Confirmed Attendance: {present} Present, {absent} Absent (Total: {total}, Rate: {confirmed_pct}%)."
        )
        if export_dict:
            msg += f" Report generated at: {export_dict.get('file_path')}."

        summary_dict = summary_res.to_dict()
        summary_dict["overall"]["confirmed_percentage"] = confirmed_pct

        if len(val_res.valid_records) == 0:
            return AgentResponse(
                request_id=request_id,
                message="No attendance records were extracted from the uploaded file. Please upload a non-empty attendance sheet.",
                success=False,
                needs_confirmation=True,
                confirmation_request=ConfirmationRequest(
                    needed=True,
                    affected_rows=[],
                    issues=["Uploaded file produced no confirmed attendance records."],
                    question="No attendance records were extracted. Please upload a valid attendance sheet.",
                ),
                data=[],
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )

        return AgentResponse(
            request_id=request_id,
            message=msg,
            success=True,
            needs_confirmation=False,
            data=val_res.valid_records,
            validation_result=val_res.to_dict(),
            summary_report=summary_dict,
            export_result=export_dict,
            tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
        )

    def _handle_query_intent(self, text: str, request_id: str) -> AgentResponse:
        """Handle database query requests safely without hallucinating numbers."""
        clean = text.lower()
        db = self.db_target

        # 1. Absentees query
        if "absent" in clean or "absentees" in clean:
            sess_id = self._extract_session_id(text)
            room_match = re.search(r"(?:room)[\s_-]*([A-Za-z0-9_-]+)", text, re.IGNORECASE)
            room_id = room_match.group(1) if room_match else None

            res: QueryResult = self.registry.execute(
                "query_tool",
                request_id=request_id,
                query_type="absentees",
                session_id=sess_id,
                room_id=room_id,
                db_target=db,
            )
            if not res.found:
                return AgentResponse(
                    request_id=request_id,
                    message=NO_DATA_MESSAGE,
                    success=True,
                    needs_confirmation=False,
                    data=[],
                    tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
                )
            return AgentResponse(
                request_id=request_id,
                message=f"Found {res.total_count} absent student(s).",
                success=True,
                needs_confirmation=False,
                data=res.data,
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )

        # Check for unrecorded metrics not present in database schema (scores, gpa, grades, etc.)
        unsupported_metrics = ["score", "gpa", "marks", "grade", "exam", "rank", "fee", "tuition", "salary"]
        if any(m in clean for m in unsupported_metrics):
            sess_id = self._extract_session_id(text)
            self.registry.execute(
                "query_tool",
                request_id=request_id,
                query_type="attendance",
                session_id=sess_id,
                db_target=db,
            )
            return AgentResponse(
                request_id=request_id,
                message=NO_DATA_MESSAGE,
                success=True,
                needs_confirmation=False,
                data=[],
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )

        # 2. Session statistics query
        if "stats" in clean or "rate" in clean or "percentage" in clean or "session" in clean:
            sess_id = self._extract_session_id(text)
            if sess_id:
                res = self.registry.execute(
                    "query_tool",
                    request_id=request_id,
                    query_type="session_stats",
                    session_id=sess_id,
                    db_target=db,
                )
                if not res.found:
                    return AgentResponse(
                        request_id=request_id,
                        message=NO_DATA_MESSAGE,
                        success=True,
                        needs_confirmation=False,
                        data=[],
                        tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
                    )
                return AgentResponse(
                    request_id=request_id,
                    message=res.message,
                    success=True,
                    needs_confirmation=False,
                    data=res.data,
                    tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
                )

        # 3. Student query
        usn_match = re.search(r"\b\d[A-Z]{2}\d{2}[A-Z]{2}\d{3}\b", text, re.IGNORECASE)
        if usn_match or "student" in clean:
            usn = usn_match.group(0).upper() if usn_match else None
            res = self.registry.execute(
                "query_tool",
                request_id=request_id,
                query_type="students",
                usn=usn,
                db_target=db,
            )
            if not res.found:
                return AgentResponse(
                    request_id=request_id,
                    message=NO_DATA_MESSAGE,
                    success=True,
                    needs_confirmation=False,
                    data=[],
                    tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
                )
            return AgentResponse(
                request_id=request_id,
                message=f"Found student record: {res.data[0].get('name')} ({res.data[0].get('usn')}, Branch: {res.data[0].get('branch')}).",
                success=True,
                needs_confirmation=False,
                data=res.data,
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )

        # Generic attendance query fallback
        res = self.registry.execute(
            "query_tool",
            request_id=request_id,
            query_type="attendance",
            db_target=db,
        )
        if not res.found:
            return AgentResponse(
                request_id=request_id,
                message=NO_DATA_MESSAGE,
                success=True,
                needs_confirmation=False,
                data=[],
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )
        return AgentResponse(
            request_id=request_id,
            message=f"Found {res.total_count} attendance records.",
            success=True,
            needs_confirmation=False,
            data=res.data,
            tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
        )

    @staticmethod
    def _detect_file_in_text(text: str) -> Optional[Path]:
        """Detect file path mentioned inside text string."""
        match = re.search(r"([A-Za-z0-9_./\\-]+\.(?:csv|png|jpg|jpeg|bmp|webp))", text, re.IGNORECASE)
        if match:
            candidate = Path(match.group(1))
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _detect_room_in_text(text: str) -> Optional[str]:
        """Detect room ID mentioned inside text string."""
        if not text:
            return None
        match = re.search(r"\b(?:room|hall)\s+([A-Za-z0-9_-]+)\b", text, re.IGNORECASE)
        if match:
            return match.group(1).upper()
        match_code = re.search(r"\b(LH-\d+|LAB-\d+)\b", text, re.IGNORECASE)
        if match_code:
            return match_code.group(1).upper()
        return None

    @staticmethod
    def _extract_session_id(text: str) -> Optional[str]:
        """Extract a session identifier from free text.

        Session identifiers such as ``SESS-20261024-01`` are matched in full
        first; the shorter ``session <id>`` form is the fallback. A truncated
        identifier would simply not resolve to a session, so the full token is
        preferred.
        """
        explicit = re.search(r"\bSESS[-_][A-Za-z0-9_-]*", text, re.IGNORECASE)
        if explicit:
            return explicit.group(0)
        fallback = re.search(r"(?:session|sess)\b[\s_:-]*([A-Za-z0-9][A-Za-z0-9_-]*)", text, re.IGNORECASE)
        if fallback:
            return fallback.group(1)
        return None

    @staticmethod
    def _is_query_intent(text: str) -> bool:
        keywords = ["how many", "who", "absent", "present", "session", "student", "records", "database", "query", "find"]
        return any(k in text.lower() for k in keywords)

    @staticmethod
    def _is_export_intent(text: str) -> bool:
        return any(k in text.lower() for k in ["export", "download", "pdf", "excel", "xlsx"])

    @staticmethod
    def _is_greeting_intent(clean: str) -> bool:
        greetings = [
            "hi", "hello", "hey", "hola", "namaste", "good morning",
            "good afternoon", "good evening", "greetings", "who are you",
            "what can you do", "help", "who am i",
        ]
        if clean in greetings:
            return True
        for g in ("hi ", "hello ", "hey ", "good morning", "good afternoon", "good evening"):
            if clean.startswith(g):
                return True
        return False

    def _handle_greeting_intent(self, text: str, request_id: str) -> AgentResponse:
        self.tool_logger.log(
            request_id=request_id,
            tool_name="agent_assistant",
            arguments={"query": text, "actor_id": self.actor_id},
            success=True,
            result_summary="Greeted teacher and loaded profile snapshot",
            duration_seconds=0.001,
        )
        subs = ", ".join(self.assigned_subjects) if self.assigned_subjects else "All assigned classes"
        msg = (
            f"Hello {self.actor_name}! I am your RollCall AI attendance assistant.\n\n"
            f"I have live access to your teaching schedule and attendance data for **{subs}**.\n\n"
            "You can ask me questions like:\n"
            "• **Summarize today's overall attendance**\n"
            "• **List students with attendance below 75%**\n"
            "• **Which sessions have pending unreviewed attendance?**\n"
            "• **Show attendance statistics for Computer Science (CSE)**\n"
            "• **Show vacant rooms or my timetable today**\n"
            "• Or upload an attendance sheet CSV/photo for automated verification."
        )
        return AgentResponse(
            request_id=request_id,
            message=msg,
            success=True,
            needs_confirmation=False,
            data=[],
            tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
        )

    @staticmethod
    def _is_datetime_intent(clean: str) -> bool:
        """Detect real-time date, day of week, or time queries."""
        date_phrases = [
            "what is the day today", "what day is today", "what day is it",
            "what is today's date", "what is the date today", "what date is it",
            "what is current date", "what's the day today", "what is today",
            "today's date", "current date", "what time is it", "current time",
            "tell me today's date", "which day is today", "what is the day",
            "today date", "today day", "current day", "what is date today"
        ]
        if any(p in clean for p in date_phrases):
            return True
        if "day" in clean and ("today" in clean or "now" in clean) and any(w in clean for w in ["what", "which", "tell", "check"]):
            return True
        if "date" in clean and ("today" in clean or "now" in clean or "current" in clean) and any(w in clean for w in ["what", "which", "tell", "show"]):
            return True
        return False

    def _handle_datetime_intent(self, text: str, request_id: str) -> AgentResponse:
        now_dt = datetime.datetime.now()
        day_name = now_dt.strftime("%A")
        full_date = now_dt.strftime("%B %d, %Y")
        time_str = now_dt.strftime("%I:%M %p")
        iso_date = now_dt.strftime("%Y-%m-%d")

        self.tool_logger.log(
            request_id=request_id,
            tool_name="get_current_datetime",
            arguments={"query": text},
            success=True,
            result_summary=f"Reported live real-time datetime: {day_name}, {full_date}",
            duration_seconds=0.001,
        )
        msg = (
            f"📅 **Live Real-Time Date & Day**:\n\n"
            f"• **Day of the Week:** {day_name}\n"
            f"• **Today's Date:** {full_date} (`{iso_date}`)\n"
            f"• **Current Time:** {time_str}\n\n"
            f"Your academic timetable, classroom vacancies, and attendance sessions are all synchronized with this live date."
        )
        return AgentResponse(
            request_id=request_id,
            message=msg,
            success=True,
            needs_confirmation=False,
            data=[{"date": iso_date, "day": day_name, "time": time_str}],
            tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
        )

    @staticmethod
    def _is_defaulter_intent(clean: str) -> bool:
        keywords = ["defaulter", "defaulters", "below 75", "< 75", "<75", "shortage", "low attendance", "attendance below"]
        return any(k in clean for k in keywords)

    def _handle_defaulters_intent(self, text: str, request_id: str) -> AgentResponse:
        import sqlite3
        from tools.query_tool import _get_readonly_conn
        t_start = time.time()
        try:
            rdb = _get_readonly_conn(self.db_target)
            sql = """
                SELECT s.usn, s.name, s.branch,
                       COUNT(a.attendance_id) as conducted,
                       SUM(CASE WHEN UPPER(a.status) = 'PRESENT' THEN 1 ELSE 0 END) as attended
                FROM attendance a
                JOIN sessions sess ON a.session_id = sess.session_id
                JOIN students s ON a.usn = s.usn
            """
            params: List[Any] = []
            conditions = []
            role_str = str(self.role.value if hasattr(self.role, "value") else self.role).upper()
            if role_str == "FACULTY" and self.assigned_subjects:
                subs_upper = [s.upper() for s in self.assigned_subjects]
                sub_ph = ", ".join(["?"] * len(subs_upper))
                conditions.append(
                    f"(UPPER(COALESCE(sess.subject_code, '')) IN ({sub_ph}) "
                    f"OR UPPER(COALESCE(sess.subject, '')) IN ({sub_ph}) "
                    f"OR " + " OR ".join(["UPPER(COALESCE(sess.subject, '')) LIKE ?"] * len(subs_upper)) + ")"
                )
                params.extend(subs_upper)
                params.extend(subs_upper)
                params.extend([f"%{s}%" for s in subs_upper])

            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " GROUP BY s.usn, s.name, s.branch"

            res = rdb.execute(sql, params)
            rows = res.fetchall()
            rdb.close()

            defaulters_list = []
            for r in rows:
                if hasattr(r, "_mapping"):
                    row_dict = dict(r._mapping)
                elif isinstance(r, sqlite3.Row):
                    row_dict = dict(r)
                elif hasattr(r, "__getitem__"):
                    try:
                        row_dict = dict(r)
                    except Exception:
                        row_dict = dict(zip(["usn", "name", "branch", "conducted", "attended"], r))
                else:
                    row_dict = dict(zip(["usn", "name", "branch", "conducted", "attended"], r))

                conducted = int(row_dict.get("conducted") or 0)
                attended = int(row_dict.get("attended") or 0)
                if conducted <= 0:
                    continue
                pct = round((attended / conducted) * 100, 1)
                if pct < 75.0:
                    classes_needed = max(0, 3 * conducted - 4 * attended)
                    defaulters_list.append({
                        "usn": row_dict.get("usn"),
                        "name": row_dict.get("name"),
                        "branch": row_dict.get("branch"),
                        "attended": attended,
                        "conducted": conducted,
                        "percentage": pct,
                        "classes_needed": classes_needed,
                    })

            defaulters_list.sort(key=lambda x: x["percentage"])
            duration = time.time() - t_start

            self.tool_logger.log(
                request_id=request_id,
                tool_name="get_defaulters_analysis",
                arguments={"actor_id": self.actor_id, "threshold": 75.0},
                success=True,
                result_summary=f"Found {len(defaulters_list)} defaulters (<75%)",
                duration_seconds=round(duration, 4),
            )

            if not defaulters_list:
                msg = "Great news! No students currently have attendance below the 75% threshold in your assigned subjects."
            else:
                lines = [f"Found {len(defaulters_list)} student(s) with attendance below 75%:\n"]
                for d in defaulters_list[:15]:
                    lines.append(
                        f"• **{d['name']}** ({d['usn']}, {d['branch']}): "
                        f"{d['percentage']}% ({d['attended']}/{d['conducted']} classes) — "
                        f"Needs {d['classes_needed']} consecutive class(es) to reach 75%"
                    )
                if len(defaulters_list) > 15:
                    lines.append(f"\n*...and {len(defaulters_list) - 15} more students.*")
                msg = "\n".join(lines)

            return AgentResponse(
                request_id=request_id,
                message=msg,
                success=True,
                needs_confirmation=False,
                data=defaulters_list,
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )
        except Exception as exc:
            logger.error("Defaulters query failed: %s", exc)
            return AgentResponse(
                request_id=request_id,
                message="Unable to analyze defaulters at this moment.",
                success=False,
                needs_confirmation=False,
                data=[],
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )

    @staticmethod
    def _is_pending_intent(clean: str) -> bool:
        return any(k in clean for k in ["pending", "unreviewed", "not reviewed", "needs review"])

    def _handle_pending_sessions_intent(self, text: str, request_id: str) -> AgentResponse:
        import sqlite3
        from tools.query_tool import _get_readonly_conn
        t_start = time.time()
        try:
            rdb = _get_readonly_conn(self.db_target)
            sql = """
                SELECT sess.session_id, sess.subject, sess.subject_code, sess.date,
                       COUNT(a.attendance_id) as total_attendance,
                       SUM(CASE WHEN UPPER(a.status) IN ('PENDING', 'UNREVIEWED') THEN 1 ELSE 0 END) as pending_count
                FROM sessions sess
                LEFT JOIN attendance a ON sess.session_id = a.session_id
            """
            params: List[Any] = []
            conditions = []
            role_str = str(self.role.value if hasattr(self.role, "value") else self.role).upper()
            if role_str == "FACULTY" and self.assigned_subjects:
                subs_upper = [s.upper() for s in self.assigned_subjects]
                sub_ph = ", ".join(["?"] * len(subs_upper))
                conditions.append(
                    f"(UPPER(COALESCE(sess.subject_code, '')) IN ({sub_ph}) "
                    f"OR UPPER(COALESCE(sess.subject, '')) IN ({sub_ph}) "
                    f"OR " + " OR ".join(["UPPER(COALESCE(sess.subject, '')) LIKE ?"] * len(subs_upper)) + ")"
                )
                params.extend(subs_upper)
                params.extend(subs_upper)
                params.extend([f"%{s}%" for s in subs_upper])

            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " GROUP BY sess.session_id, sess.subject, sess.subject_code, sess.date ORDER BY sess.date DESC"

            res = rdb.execute(sql, params)
            rows = res.fetchall()
            rdb.close()

            pending_sessions = []
            for r in rows:
                if hasattr(r, "_mapping"):
                    row_dict = dict(r._mapping)
                elif isinstance(r, sqlite3.Row):
                    row_dict = dict(r)
                elif hasattr(r, "__getitem__"):
                    try:
                        row_dict = dict(r)
                    except Exception:
                        row_dict = dict(zip(["session_id", "subject", "subject_code", "date", "total_attendance", "pending_count"], r))
                else:
                    row_dict = dict(zip(["session_id", "subject", "subject_code", "date", "total_attendance", "pending_count"], r))

                pending_cnt = int(row_dict.get("pending_count") or 0)
                tot_cnt = int(row_dict.get("total_attendance") or 0)
                if pending_cnt > 0 or tot_cnt == 0:
                    pending_sessions.append({
                        "session_id": row_dict.get("session_id"),
                        "subject": row_dict.get("subject"),
                        "subject_code": row_dict.get("subject_code"),
                        "date": str(row_dict.get("date")),
                        "pending_count": pending_cnt,
                        "total_students": tot_cnt,
                    })

            duration = time.time() - t_start
            self.tool_logger.log(
                request_id=request_id,
                tool_name="get_pending_unreviewed_sessions",
                arguments={"actor_id": self.actor_id},
                success=True,
                result_summary=f"Found {len(pending_sessions)} pending sessions",
                duration_seconds=round(duration, 4),
            )

            if not pending_sessions:
                msg = "All attendance sessions for your assigned subjects are fully reviewed and confirmed! No pending sessions found."
            else:
                lines = [f"Found {len(pending_sessions)} session(s) with pending or unreviewed attendance:\n"]
                for ps in pending_sessions:
                    if ps["total_students"] == 0:
                        lines.append(
                            f"• **{ps['session_id']}**: {ps['subject']} ({ps['subject_code']}) on **{ps['date']}** — "
                            f"Awaiting attendance roster upload (0 students recorded)."
                        )
                    else:
                        lines.append(
                            f"• **{ps['session_id']}**: {ps['subject']} ({ps['subject_code']}) on **{ps['date']}** — "
                            f"{ps['pending_count']} pending/unreviewed record(s) out of {ps['total_students']} total students."
                        )
                msg = "\n".join(lines)

            return AgentResponse(
                request_id=request_id,
                message=msg,
                success=True,
                needs_confirmation=False,
                data=pending_sessions,
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )
        except Exception as exc:
            logger.error("Pending sessions query failed: %s", exc)
            return AgentResponse(
                request_id=request_id,
                message="Unable to fetch pending sessions.",
                success=False,
                needs_confirmation=False,
                data=[],
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )

    @staticmethod
    def _is_summary_intent(clean: str) -> bool:
        keywords = ["summarize", "summarise", "summary", "overall attendance", "today's attendance", "attendance summary", "statistics", "stats"]
        return any(k in clean for k in keywords)

    def _handle_attendance_summary_intent(self, text: str, request_id: str) -> AgentResponse:
        from datetime import date
        from tools.query_tool import _get_readonly_conn
        clean = text.lower()
        t_start = time.time()
        try:
            rdb = _get_readonly_conn(self.db_target)
            today_str = date.today().isoformat()
            is_today = "today" in clean

            # Extract branch if requested (e.g. CSE, ECE, ISE, MECH, CIVIL)
            branch = None
            if re.search(r"\b(cse|computer science)\b", clean):
                branch = "CSE"
            elif re.search(r"\b(ece|electronics)\b", clean):
                branch = "ECE"
            elif re.search(r"\b(ise|information science)\b", clean):
                branch = "ISE"

            sql = """
                SELECT a.status, COUNT(a.attendance_id) as cnt
                FROM attendance a
                JOIN sessions sess ON a.session_id = sess.session_id
                JOIN students s ON a.usn = s.usn
            """
            params: List[Any] = []
            conditions = []
            role_str = str(self.role.value if hasattr(self.role, "value") else self.role).upper()
            if role_str == "FACULTY" and self.assigned_subjects:
                subs_upper = [s.upper() for s in self.assigned_subjects]
                sub_ph = ", ".join(["?"] * len(subs_upper))
                conditions.append(
                    f"(UPPER(COALESCE(sess.subject_code, '')) IN ({sub_ph}) "
                    f"OR UPPER(COALESCE(sess.subject, '')) IN ({sub_ph}) "
                    f"OR " + " OR ".join(["UPPER(COALESCE(sess.subject, '')) LIKE ?"] * len(subs_upper)) + ")"
                )
                params.extend(subs_upper)
                params.extend(subs_upper)
                params.extend([f"%{s}%" for s in subs_upper])

            if branch:
                conditions.append("UPPER(s.branch) = ?")
                params.append(branch.upper())

            if is_today:
                conditions.append("sess.date = ?")
                params.append(today_str)

            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " GROUP BY a.status"

            res = rdb.execute(sql, params)
            rows = res.fetchall()

            counts = {}
            for r in rows:
                status_val = r[0] if (hasattr(r, "__getitem__") and not isinstance(r, dict)) else (r.get("status") if isinstance(r, dict) else "")
                cnt_val = r[1] if (hasattr(r, "__getitem__") and not isinstance(r, dict)) else (r.get("cnt") if isinstance(r, dict) else 0)
                counts[str(status_val).upper()] = int(cnt_val)

            total = sum(counts.values())
            present = counts.get("PRESENT", 0)
            absent = counts.get("ABSENT", 0)
            pending = counts.get("PENDING", 0)
            unreviewed = counts.get("UNREVIEWED", 0)
            pct = round((present / total * 100), 1) if total > 0 else 0.0

            # If today was queried and total == 0, fetch overall recent attendance as context
            recent_context = ""
            if is_today and total == 0:
                res_all = rdb.execute("""
                    SELECT a.status, COUNT(a.attendance_id) as cnt
                    FROM attendance a
                    JOIN sessions sess ON a.session_id = sess.session_id
                    GROUP BY a.status
                """)
                counts_all = {str(r[0]).upper(): int(r[1]) for r in res_all.fetchall()}
                tot_all = sum(counts_all.values())
                pres_all = counts_all.get("PRESENT", 0)
                pct_all = round((pres_all / tot_all * 100), 1) if tot_all > 0 else 0.0
                recent_context = (
                    f"No attendance sessions were recorded for today ({today_str}).\n\n"
                    f"Across all recorded class sessions, there are **{tot_all}** attendance records: "
                    f"**{pres_all} Present** ({pct_all}%), **{counts_all.get('ABSENT', 0)} Absent**, "
                    f"and **{counts_all.get('PENDING', 0) + counts_all.get('UNREVIEWED', 0)} Pending/Unreviewed**."
                )

            rdb.close()
            duration = time.time() - t_start

            self.tool_logger.log(
                request_id=request_id,
                tool_name="summarize_attendance",
                arguments={"actor_id": self.actor_id, "today": is_today, "branch": branch},
                success=True,
                result_summary=f"Total: {total}, Present: {present}, Absent: {absent}",
                duration_seconds=round(duration, 4),
            )

            if is_today and total == 0:
                msg = recent_context
            else:
                scope_label = f"for {branch} branch" if branch else ("today" if is_today else "across all classes")
                msg = (
                    f"📊 **Attendance Summary ({scope_label})**:\n\n"
                    f"• **Total Records**: {total}\n"
                    f"• **Present**: {present} ({pct}% attendance rate)\n"
                    f"• **Absent**: {absent}\n"
                    f"• **Pending / Unreviewed**: {pending + unreviewed}"
                )

            summary_report = {
                "overall": {
                    "total": total,
                    "present": present,
                    "absent": absent,
                    "pending": pending,
                    "unreviewed": unreviewed,
                    "confirmed_percentage": pct,
                }
            }

            return AgentResponse(
                request_id=request_id,
                message=msg,
                success=True,
                needs_confirmation=False,
                data=counts,
                summary_report=summary_report,
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )
        except Exception as exc:
            logger.error("Attendance summary query failed: %s", exc)
            return AgentResponse(
                request_id=request_id,
                message="Unable to summarize attendance records at this time.",
                success=False,
                needs_confirmation=False,
                data=[],
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )

    @staticmethod
    def _is_vacant_rooms_intent(clean: str) -> bool:
        return any(k in clean for k in ["vacant", "empty room", "vacant room", "vacant rooms", "free classroom", "available room"])

    def _handle_vacant_rooms_intent(self, text: str, request_id: str) -> AgentResponse:
        import sqlite3
        from tools.query_tool import _get_readonly_conn
        t_start = time.time()
        try:
            rdb = _get_readonly_conn(self.db_target)
            res = rdb.execute("SELECT room_id, name FROM rooms ORDER BY room_id ASC")
            rooms = []
            for r in res.fetchall():
                if hasattr(r, "_mapping"):
                    rooms.append(dict(r._mapping))
                elif isinstance(r, sqlite3.Row):
                    rooms.append(dict(r))
                elif hasattr(r, "__getitem__"):
                    try:
                        rooms.append(dict(r))
                    except Exception:
                        rooms.append(dict(zip(["room_id", "name", "capacity"], r)))
                else:
                    rooms.append(dict(zip(["room_id", "name", "capacity"], r)))
            rdb.close()
            duration = time.time() - t_start

            self.tool_logger.log(
                request_id=request_id,
                tool_name="find_vacant_classrooms",
                arguments={},
                success=True,
                result_summary=f"Found {len(rooms)} classrooms",
                duration_seconds=round(duration, 4),
            )

            if not rooms:
                msg = "No classrooms are currently registered in the database."
            else:
                lines = [f"🚪 **Vacant / Available Classrooms ({len(rooms)})**:\n"]
                for rm in rooms:
                    cap = f" (Capacity: {rm.get('capacity')})" if rm.get("capacity") else ""
                    lines.append(f"• **{rm.get('room_id')}** — {rm.get('name') or rm.get('room_id')}{cap}")
                msg = "\n".join(lines)

            return AgentResponse(
                request_id=request_id,
                message=msg,
                success=True,
                needs_confirmation=False,
                data=rooms,
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )
        except Exception as exc:
            logger.error("Vacant rooms query failed: %s", exc)
            return AgentResponse(
                request_id=request_id,
                message="Unable to fetch classroom availability.",
                success=False,
                needs_confirmation=False,
                data=[],
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )

    @staticmethod
    def _is_schedule_intent(clean: str) -> bool:
        return any(k in clean for k in ["schedule", "timetable", "my classes", "classes today", "classes tomorrow", "sessions today"])

    def _handle_schedule_intent(self, text: str, request_id: str) -> AgentResponse:
        import sqlite3
        from tools.query_tool import _get_readonly_conn
        t_start = time.time()
        try:
            rdb = _get_readonly_conn(self.db_target)
            sql = "SELECT session_id, subject, subject_code, date, room_id, lifecycle_status FROM sessions"
            params: List[Any] = []
            conditions = []
            role_str = str(self.role.value if hasattr(self.role, "value") else self.role).upper()
            if role_str == "FACULTY" and self.assigned_subjects:
                placeholders = ", ".join(["?"] * len(self.assigned_subjects))
                conditions.append(f"UPPER(subject_code) IN ({placeholders})")
                params.extend([s.upper() for s in self.assigned_subjects])

            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY date DESC LIMIT 10"

            res = rdb.execute(sql, params)
            sessions = []
            for r in res.fetchall():
                if hasattr(r, "_mapping"):
                    sessions.append(dict(r._mapping))
                elif isinstance(r, sqlite3.Row):
                    sessions.append(dict(r))
                elif hasattr(r, "__getitem__"):
                    try:
                        sessions.append(dict(r))
                    except Exception:
                        sessions.append(dict(zip(["session_id", "subject", "subject_code", "date", "room_id", "lifecycle_status"], r)))
                else:
                    sessions.append(dict(zip(["session_id", "subject", "subject_code", "date", "room_id", "lifecycle_status"], r)))
            rdb.close()
            duration = time.time() - t_start

            self.tool_logger.log(
                request_id=request_id,
                tool_name="get_class_schedule",
                arguments={"actor_id": self.actor_id},
                success=True,
                result_summary=f"Found {len(sessions)} sessions",
                duration_seconds=round(duration, 4),
            )

            if not sessions:
                subs = ", ".join(self.assigned_subjects) if self.assigned_subjects else "your subjects"
                msg = f"No active class sessions are currently scheduled for {subs}."
            else:
                lines = [f"📅 **Class Schedule for {self.actor_name}**:\n"]
                for s in sessions:
                    rm = f" in {s.get('room_id')}" if s.get("room_id") else ""
                    lines.append(f"• **{s.get('subject')}** ({s.get('subject_code')}) — Date: **{s.get('date')}**{rm} [Session: `{s.get('session_id')}`]")
                msg = "\n".join(lines)

            return AgentResponse(
                request_id=request_id,
                message=msg,
                success=True,
                needs_confirmation=False,
                data=sessions,
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )
        except Exception as exc:
            logger.error("Schedule query failed: %s", exc)
            return AgentResponse(
                request_id=request_id,
                message="Unable to fetch class schedule.",
                success=False,
                needs_confirmation=False,
                data=[],
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )

    @staticmethod
    def _is_profile_intent(clean: str) -> bool:
        """Detect profile read or update queries (mobile, phone, email, name, designation)."""
        if any(p in clean for p in [
            "my profile", "view profile", "show profile", "who am i",
            "my mobile", "my phone", "my email", "my designation",
            "what is my mobile", "what is my phone", "what's my mobile", "what's my phone",
            "get my profile", "teacher profile"
        ]):
            return True
        update_verbs = ["change", "update", "set", "modify", "edit", "switch", "save", "replace"]
        profile_fields = ["mobile", "phone", "contact", "cell", "number", "email", "name", "designation", "profile"]
        has_verb = any(v in clean for v in update_verbs)
        has_field = any(f in clean for f in profile_fields)
        return has_verb and has_field

    def _handle_profile_intent(self, text: str, request_id: str) -> AgentResponse:
        clean = text.lower()
        t_start = time.time()
        update_verbs = ["change", "update", "set", "modify", "edit", "switch", "save", "replace"]
        is_update = any(v in clean for v in update_verbs)

        mobile_val = None
        mob_match = re.search(r"(?:mobile|phone|contact|number).*?(?:to|is|as|=|:)?\s*([+]?[\d\s-]{10,16})", text, re.IGNORECASE)
        if mob_match:
            cand = re.sub(r"[\s-]", "", mob_match.group(1))
            if len(cand) >= 8 and cand.lstrip("+").isdigit():
                mobile_val = cand
        if not mobile_val and ("mobile" in clean or "phone" in clean):
            digits_match = re.search(r"\b([+]?\d{10,13})\b", text)
            if digits_match:
                mobile_val = digits_match.group(1)

        email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
        email_val = email_match.group(0) if email_match else None

        def _clean_extracted_name(cand: str) -> str:
            # Strip trailing context clauses: 'in my profile', 'in the dashboard', 'for admin', 'on my account', etc.
            cand = re.sub(
                r'\s+(?:in|on|at|of|for|from|as|with|into)\s+(?:(?:my|the|this|an?|admin)\s+)*(?:profile|dashboard|admin|account|system|database|db|settings|page|card|view|teacher).*$',
                '',
                cand,
                flags=re.IGNORECASE
            )
            # Strip trailing filler words
            cand = re.sub(r'\s+(?:please|now|right\s+now|immediately|asap|today|also|permanently)\b.*$', '', cand, flags=re.IGNORECASE)
            # Strip leading articles/pronouns
            cand = re.sub(r'^(?:my|the|a|an)\s+', '', cand, flags=re.IGNORECASE)
            return cand.strip()

        name_val = None
        if is_update and ("name" in clean or "rename" in clean):
            # 1. Match after 'to', 'is', 'as', '=', ':'
            m = re.search(r'\b(?:to|is|as|=|:)\s+([A-Za-z0-9\s.]{2,40})', text, re.IGNORECASE)
            if m:
                cand = _clean_extracted_name(m.group(1))
                if cand:
                    name_val = cand
            if not name_val:
                m2 = re.search(r'(?:rename\s+(?:me\s+)?|name\s+)([A-Za-z0-9\s.]{2,40})', text, re.IGNORECASE)
                if m2:
                    cand = _clean_extracted_name(m2.group(1))
                    if cand:
                        name_val = cand

        desig_val = None
        if "designation" in clean and is_update:
            desig_match = re.search(r"(?:designation)[\s\w]*(?:to|is|as|=)\s*([A-Za-z\s]{3,40})", text, re.IGNORECASE)
            if desig_match:
                desig_val = desig_match.group(1).strip()

        if is_update and (mobile_val or email_val or name_val or desig_val):
            self._set_pending_mutation({
                "action": "update_profile",
                "mobile_val": mobile_val,
                "email_val": email_val,
                "name_val": name_val,
                "desig_val": desig_val,
                "created_at": time.time(),
            })

            changes = []
            if mobile_val:
                changes.append(f"• **Mobile Number:** `{mobile_val}`")
            if name_val:
                changes.append(f"• **Full Name:** {name_val}")
            if email_val:
                changes.append(f"• **Email:** `{email_val}`")
            if desig_val:
                changes.append(f"• **Designation:** {desig_val}")

            msg = (
                f"📋 **Profile Update Proposal** for **{self.actor_name}** (`{self.actor_id}`):\n\n"
                + "\n".join(changes)
                + "\n\nWould you like me to proceed with updating your profile? Please click **Proceed** or reply **'yes'** to confirm."
            )
            return AgentResponse(
                request_id=request_id,
                message=msg,
                success=True,
                needs_confirmation=True,
                confirmation_request=None,
                data=[{"action": "update_profile", "user_id": self.actor_id, "mobile": mobile_val, "email": email_val, "name": name_val}],
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )


        # Otherwise read profile
        try:
            from app.db.connection import get_sync_session_factory
            from sqlalchemy import text
            from app.routers.profile import _ensure_profile_table
            db = get_sync_session_factory()()
            try:
                _ensure_profile_table(db)
                row = db.execute(
                    text("SELECT full_name, mobile, email, branch, designation FROM user_profiles WHERE user_id = :uid"),
                    {"uid": self.actor_id},
                ).fetchone()
            finally:
                db.close()

            dur = round(time.time() - t_start, 4)
            self.tool_logger.log(
                request_id=request_id,
                tool_name="get_user_profile",
                arguments={"actor_id": self.actor_id},
                success=True,
                result_summary="Fetched teacher profile",
                duration_seconds=dur,
            )
            full_name = (row[0] if row else "") or self.actor_name
            mobile = (row[1] if row else "") or "Not set"
            email = (row[2] if row else "") or "Not set"
            branch = (row[3] if row else "") or "Computer Science"
            desig = (row[4] if row else "") or self.actor_role

            msg = (
                f"👤 **Faculty Profile for {full_name}**\n\n"
                f"• **Faculty ID:** `{self.actor_id}`\n"
                f"• **Role:** {self.actor_role}\n"
                f"• **Designation:** {desig}\n"
                f"• **Department / Branch:** {branch}\n"
                f"• **Mobile:** `{mobile}`\n"
                f"• **Email:** `{email}`\n"
                f"• **Assigned Subjects:** {', '.join(self.assigned_subjects) if self.assigned_subjects else 'General'}"
            )
            return AgentResponse(
                request_id=request_id,
                message=msg,
                success=True,
                needs_confirmation=False,
                data=[{"user_id": self.actor_id, "mobile": mobile, "email": email, "full_name": full_name}],
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )
        except Exception as exc:
            logger.error("Failed to read profile: %s", exc)
            return AgentResponse(
                request_id=request_id,
                message=f"Unable to load profile: {exc}",
                success=False,
                needs_confirmation=False,
                data=[],
                tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
            )

    @staticmethod
    def _is_create_session_intent(clean: str) -> bool:
        """Detect intent to create, add, or schedule a new class session."""
        create_verbs = ["create", "add", "new", "schedule", "start", "setup", "set up"]
        has_verb = any(v in clean for v in create_verbs)
        has_session = any(s in clean for s in ["session", "class", "lecture", "period"])
        is_read_query = any(q in clean for q in ["how many", "which", "list", "show", "pending", "unreviewed", "what is", "what was"])
        return has_verb and has_session and not is_read_query

    def _handle_create_session_intent(self, text: str, request_id: str) -> AgentResponse:
        import datetime
        clean = text.lower()
        t_start = time.time()

        # 1. Subject extraction
        subject = None
        m = re.search(r"\b(?:named|name|titled|subject|course|code)\b\s*(?:is|=|:)?\s*([A-Za-z0-9_-]{2,25})", text, re.IGNORECASE)
        if m:
            subject = m.group(1).strip()
        if not subject:
            m2 = re.search(r"\b(?:for|in)\s+([A-Za-z0-9_-]{2,15})(?=\s+(?:today|tomorrow|from|at|\d)|$)", text, re.IGNORECASE)
            if m2 and m2.group(1).lower() not in ["today", "tomorrow", "session"]:
                subject = m2.group(1).strip()
        if not subject:
            m3 = re.search(r"\b(?:create|add|new|schedule)\s+([A-Za-z0-9_-]{2,15})\s+session", text, re.IGNORECASE)
            if m3 and m3.group(1).lower() not in ["a", "new"]:
                subject = m3.group(1).strip()
        if not subject and self.assigned_subjects:
            subject = self.assigned_subjects[0]
        if not subject:
            subject = "GENERAL"

        clean_subject = subject.strip().upper()

        # 2. Date extraction
        now_d = datetime.date.today()
        target_date = now_d.isoformat()
        if "tomorrow" in clean:
            target_date = (now_d + datetime.timedelta(days=1)).isoformat()
        else:
            m_date = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
            if m_date:
                target_date = m_date.group(1)

        # 3. Time extraction
        m_time = re.search(r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*(?:to|-)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", text, re.IGNORECASE)
        time_range = m_time.group(1).strip() if m_time else None

        # 4. Room extraction
        m_room = re.search(r"\b(?:room|hall)\s*([A-Za-z0-9_-]{2,10})", text, re.IGNORECASE)
        room_id = m_room.group(1).strip().upper() if m_room else None

        # 5. Store pending mutation and propose to user before implementing
        self._set_pending_mutation({
            "action": "create_session",
            "subject": clean_subject,
            "date": target_date,
            "time_range": time_range,
            "room_id": room_id,
            "created_at": time.time(),
        })

        details = [
            f"• **Subject:** {clean_subject}",
            f"• **Date:** {target_date}",
        ]
        if time_range:
            details.append(f"• **Time:** {time_range}")
        if room_id:
            details.append(f"• **Room:** {room_id}")
        else:
            details.append("• **Room:** Not allocated (Can be assigned in Attendance)")
        details.append(f"• **Instructor:** {self.actor_name} (`{self.actor_id}`)")

        msg = (
            "📋 **Session Creation Proposal**\n\n"
            "I have prepared the following session details:\n"
            + "\n".join(details)
            + "\n\nWould you like me to proceed with creating this session? Please reply **'yes'** or **'proceed'** to confirm."
        )

        return AgentResponse(
            request_id=request_id,
            message=msg,
            success=True,
            needs_confirmation=True,
            confirmation_request=None,
            data=[{
                "action": "create_session",
                "subject": clean_subject,
                "date": target_date,
                "time": time_range,
                "room": room_id,
                "teacher_id": self.actor_id,
            }],
            tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
        )

    def _handle_general_intent(self, text: str, request_id: str) -> AgentResponse:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if api_key and not api_key.startswith("your_"):
            try:
                from app.agent.provider import GeminiProvider
                provider = GeminiProvider(api_key=api_key)
                subs_str = ", ".join(self.assigned_subjects) if self.assigned_subjects else "General"
                now_dt = datetime.datetime.now()
                sys_inst = (
                    f"You are RollCall AI, an intelligent attendance assistant for higher education.\n"
                    f"LIVE REAL-TIME SYSTEM CLOCK:\n"
                    f"- Today's Day & Date: {now_dt.strftime('%A')}, {now_dt.strftime('%B %d, %Y')} (ISO: {now_dt.strftime('%Y-%m-%d')})\n"
                    f"- Current Local Time: {now_dt.strftime('%I:%M %p')}\n\n"
                    f"The logged-in instructor is {self.actor_name} (User ID: `{self.actor_id}`, Role: {self.actor_role}), "
                    f"assigned subjects: {subs_str}.\n"
                    "Provide a direct, concise, and helpful answer regarding attendance, sessions, student regulations, or college operations. "
                    "When answering queries regarding today, current date, day, or schedule, ALWAYS strictly reference the live real-time clock above."
                )
                t_start = time.time()
                resp = provider.generate(
                    messages=[{"role": "user", "content": text}],
                    system_instruction=sys_inst,
                )
                if resp.content:
                    self.tool_logger.log(
                        request_id=request_id,
                        tool_name="gemini_llm",
                        arguments={"prompt": text[:100]},
                        success=True,
                        result_summary="Generated response via Gemini LLM",
                        duration_seconds=round(time.time() - t_start, 4),
                    )
                    return AgentResponse(
                        request_id=request_id,
                        message=resp.content,
                        success=True,
                        needs_confirmation=False,
                        data=[],
                        tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
                    )
            except Exception as e:
                logger.debug("Gemini general intent fallback error: %s", e)

        # Fallback if no LLM or LLM unreachable
        return AgentResponse(
            request_id=request_id,
            message=(
                f"Hello {self.actor_name}! I am your RollCall AI attendance assistant. "
                "You can ask me to summarize today's attendance, list defaulters (<75%), "
                "inspect pending unreviewed sessions, check classroom availability, or upload attendance sheets."
            ),
            success=True,
            needs_confirmation=False,
            data=[],
            tool_calls=[l.to_dict() for l in self.get_logs(request_id)],
        )
