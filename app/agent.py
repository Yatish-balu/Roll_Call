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
import pandas as pd

from tools.read_csv_tool import read_csv_tool
from tools.read_photo_tool import read_photo_tool, PhotoExtractionResult
from tools.validate_tool import validate_tool, ValidationResult
from tools.summary_tool import summary_tool, SummaryReport
from tools.query_tool import query_tool, QueryResult, NO_DATA_MESSAGE
from tools.export_tool import export_tool, ExportResult

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

    def __init__(self, tool_logger: ToolLogger) -> None:
        self.logger = tool_logger
        self.tools: Dict[str, ToolDefinition] = {}
        self.validated_requests: set[str] = set()
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

        start_time = time.perf_counter()
        try:
            result = tool_def.handler(**kwargs)
            duration = time.perf_counter() - start_time

            # Track successful validation
            if name == "validate_tool" and isinstance(result, ValidationResult) and result.is_valid:
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
                handler=lambda source, **kw: read_csv_tool(source=source, **_clean(kw)),
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
                handler=lambda image_path, **kw: read_photo_tool(image_path=image_path, **_clean(kw)),
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
                handler=lambda data, **kw: validate_tool(data=data, **_clean(kw)),
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
                handler=lambda data, **kw: summary_tool(data=data, **_clean(kw)),
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
                            "enum": ["attendance", "session_stats", "absentees", "students", "sql"],
                            "description": "Category of query to perform.",
                        },
                        "session_id": {"type": "string", "description": "Target session ID."},
                        "room_id": {"type": "string", "description": "Filter by room ID."},
                        "branch": {"type": "string", "description": "Filter by department/branch."},
                        "usn": {"type": "string", "description": "Filter by student USN."},
                    },
                    "required": ["query_type"],
                },
                handler=lambda query_type, **kw: query_tool(query_type=query_type, **_clean(kw)),
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
                handler=lambda data, **kw: export_tool(data=data, **_clean(kw)),
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
        db_target: Optional[Union[str, sqlite3.Connection]] = None,
        tool_logger: Optional[ToolLogger] = None,
        confidence_threshold: float = CONFIDENCE_CONFIRMATION_THRESHOLD,
    ) -> None:
        self.db_target = db_target
        self.logger = tool_logger or ToolLogger()
        self.registry = ToolRegistry(tool_logger=self.logger)
        self.confidence_threshold = confidence_threshold

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

        # 2. Database question / query request
        if self._is_query_intent(input_str):
            return self._handle_query_intent(input_str, req_id)

        # 3. Direct export request
        if self._is_export_intent(input_str):
            return AgentResponse(
                request_id=req_id,
                message="Cannot export: no validated attendance dataset or summary was provided. Please supply an attendance sheet first.",
                success=False,
                needs_confirmation=False,
            )

        # 4. Direct summary without file
        if "summary" in input_str.lower() or "summarise" in input_str.lower():
            return AgentResponse(
                request_id=req_id,
                message="Validation required before summarising: Please provide an attendance CSV or photo file.",
                success=False,
                needs_confirmation=False,
            )

        # 5. Fallback unhandled question
        return AgentResponse(
            request_id=req_id,
            message=NO_DATA_MESSAGE,
            success=False,
            needs_confirmation=False,
        )

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
        else:
            return AgentResponse(
                request_id=request_id,
                message=f"Unsupported file format '{suffix}'. Supported formats: .csv, .png, .jpg, .jpeg.",
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
            sess_match = re.search(r"(?:session|sess)[\s_-]*([A-Za-z0-9_-]+)", text, re.IGNORECASE)
            room_match = re.search(r"(?:room)[\s_-]*([A-Za-z0-9_-]+)", text, re.IGNORECASE)
            sess_id = sess_match.group(1) if sess_match else None
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
            sess_match = re.search(r"(?:session|sess)[\s_-]*([A-Za-z0-9_-]+)", text, re.IGNORECASE)
            self.registry.execute(
                "query_tool",
                request_id=request_id,
                query_type="attendance",
                session_id=sess_match.group(1) if sess_match else None,
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
            sess_match = re.search(r"(?:session|sess)[\s_-]*([A-Za-z0-9_-]+)", text, re.IGNORECASE)
            if sess_match:
                sess_id = sess_match.group(1)
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
    def _is_query_intent(text: str) -> bool:
        keywords = ["how many", "who", "absent", "present", "session", "student", "records", "database", "query", "find"]
        return any(k in text.lower() for k in keywords)

    @staticmethod
    def _is_export_intent(text: str) -> bool:
        return any(k in text.lower() for k in ["export", "download", "pdf", "excel", "xlsx"])
