"""Agent and Chat interaction Pydantic v2 schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ToolCallLogSchema(BaseModel):
    """Schema representing an individual tool execution record."""

    log_id: str = Field(..., description="Unique tool log ID")
    request_id: str = Field(..., description="Agent request ID context")
    timestamp: str = Field(..., description="ISO timestamp of invocation")
    tool_name: str = Field(..., description="Registered tool name")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Sanitized invocation parameters")
    success: bool = Field(..., description="Whether the tool succeeded")
    result_summary: str = Field(..., description="Summary of output or findings")
    duration_seconds: float = Field(..., ge=0.0, description="Duration in seconds")
    error_message: Optional[str] = Field(None, description="Error message if failed")

    model_config = ConfigDict(from_attributes=True)


class ConfirmationRequestSchema(BaseModel):
    """Schema representing a confirmation requirement sent to the user when guardrails trigger."""

    needed: bool = Field(default=True, description="Whether user confirmation is required")
    affected_rows: List[Dict[str, Any]] = Field(default_factory=list, description="Problematic or low-confidence rows")
    issues: List[str] = Field(default_factory=list, description="List of detected anomalies or issues")
    question: str = Field(..., description="Clarifying question posed to the user")

    model_config = ConfigDict(from_attributes=True)


class AgentRequest(BaseModel):
    """Schema for requesting agent assistance or workflow execution."""

    prompt: Optional[str] = Field(None, description="Natural language instruction or query")
    file_path: Optional[str] = Field(None, description="Path to CSV or photo file to process")
    session_id: Optional[str] = Field(None, description="Contextual attendance session ID")
    user_confirmation: Optional[str] = Field(
        None, description="Explicit user confirmation ('yes', 'proceed', or corrective instructions)"
    )
    request_id: Optional[str] = Field(None, description="Optional caller-supplied request correlation ID")


class ChatQueryRequest(BaseModel):
    """Schema for natural-language attendance queries."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="Question about attendance, records, or students",
    )
    session_id: Optional[str] = Field(
        None,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]{1,64}$",
        description="Optional target session identifier",
    )


class FileUploadResponse(BaseModel):
    """Schema for file upload responses."""

    filename: str = Field(..., description="Name of the uploaded file")
    file_path: str = Field(..., description="Saved temporary path on server")
    file_type: str = Field(..., description="Detected file category ('csv' or 'photo')")
    size_bytes: int = Field(..., ge=0, description="File size in bytes")


class AgentResponseSchema(BaseModel):
    """Structured response schema returned from the agent loop."""

    request_id: str = Field(..., description="Unique request identifier")
    message: str = Field(..., description="Agent message or answer")
    success: bool = Field(..., description="Whether the workflow succeeded without unhandled errors")
    needs_confirmation: bool = Field(..., description="Whether execution paused for human-in-the-loop confirmation")
    confirmation_request: Optional[ConfirmationRequestSchema] = Field(
        None, description="Details of the confirmation required"
    )
    data: Optional[Any] = Field(None, description="Extracted records or raw data")
    validation_result: Optional[Dict[str, Any]] = Field(None, description="Validation summary if applicable")
    summary_report: Optional[Dict[str, Any]] = Field(None, description="Calculated attendance analytics")
    export_result: Optional[Dict[str, Any]] = Field(None, description="Export output details if exported")
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list, description="Audit trace of invoked tools")

    model_config = ConfigDict(from_attributes=True)


class AgentConfirmRequest(BaseModel):
    """Payload to confirm or reject extracted/validated attendance records."""

    session_id: str = Field(..., min_length=1, description="Target session ID")
    confirmed: bool = Field(..., description="True to confirm and commit, False to reject")
    records: List[Dict[str, Any]] = Field(default_factory=list, description="Validated records to commit")
    request_id: Optional[str] = Field(None, description="Correlation request ID")
    source: Optional[str] = Field("AGENT_CONFIRMED", description="Audit source")


class AgentStatusResponse(BaseModel):
    """Status of AI models, providers, and guardrails."""

    status: str = Field("ready", description="Overall agent system status")
    gemini_configured: bool = Field(..., description="Whether Gemini API key is configured")
    ollama_available: bool = Field(..., description="Whether local Ollama instance is reachable")
    easyocr_available: bool = Field(True, description="Whether EasyOCR fallback engine is available")
    confidence_threshold: float = Field(0.80, description="Confidence threshold triggering mandatory human confirmation")
    available_tools: List[str] = Field(default_factory=list, description="Registered tool names")


# ---------------------------------------------------------------------------
# N7: two-step AI attendance editing (proposal -> explicit confirmation)
# ---------------------------------------------------------------------------


class AttendanceEditProposalRequest(BaseModel):
    """Request to propose an attendance modification through the AI assistant.

    The AI (or the client) may only *suggest* the intent. The backend resolves
    the session and student against the database, authorizes the caller and
    stores the proposal; it never trusts a client-supplied role or actor.
    """

    query: Optional[str] = Field(
        None,
        max_length=1000,
        description="Natural-language attendance edit request, e.g. 'mark 1MS21CS001 absent in SESS-001'.",
    )
    session_id: Optional[str] = Field(
        None, max_length=50, description="Optional explicit target session id"
    )
    usn: Optional[str] = Field(
        None, max_length=50, description="Optional explicit target student USN"
    )
    new_status: Optional[str] = Field(
        None,
        max_length=20,
        description="Optional explicit proposed status (PRESENT, ABSENT, PENDING, UNREVIEWED)",
    )
    reason: Optional[str] = Field(
        None, max_length=500, description="Optional note stored with the audit record"
    )
    request_id: Optional[str] = Field(None, description="Optional caller correlation id")


class AttendanceEditProposalResponse(BaseModel):
    """Response of a proposal step.

    ``status`` is ``proposed`` when a pending confirmation was created, or
    ``clarification_required`` when the request could not be resolved
    unambiguously (no pending edit is created in that case).
    """

    status: str = Field(..., description="'proposed' or 'clarification_required'")
    success: bool = Field(True, description="Whether the proposal step succeeded")
    needs_confirmation: bool = Field(
        False, description="True when a pending confirmation is awaiting the user"
    )
    confirmation_id: Optional[str] = Field(
        None,
        description="Identifier of the pending confirmation (the only value the confirm step accepts)",
    )
    expires_at: Optional[str] = Field(None, description="UTC expiry of the pending confirmation")
    expires_in_seconds: Optional[int] = Field(
        None, description="Validity window of the pending confirmation in seconds"
    )
    session: Optional[Dict[str, Any]] = Field(None, description="Resolved session summary")
    student: Optional[Dict[str, Any]] = Field(None, description="Resolved student summary")
    current_status: Optional[str] = Field(None, description="Attendance status before the change")
    proposed_status: Optional[str] = Field(None, description="Attendance status that would be applied")
    confirmation_request: Optional[ConfirmationRequestSchema] = Field(
        None, description="Confirmation card payload for the frontend"
    )
    clarification: Optional[Dict[str, Any]] = Field(
        None, description="Clarification request when the intent could not be resolved"
    )
    message: str = Field(..., description="Human readable status message")
    request_id: Optional[str] = Field(None, description="Correlation id")
    tool_calls: List[Dict[str, Any]] = Field(
        default_factory=list, description="Audit trace of invoked tools"
    )

    model_config = ConfigDict(from_attributes=True)


class AttendanceEditConfirmRequest(BaseModel):
    """Request to confirm a previously proposed attendance modification.

    Only the confirmation identifier is accepted. The student, session and
    proposed status are taken from the stored proposal and the actor identity
    and role from the verified authentication context, so a client can never
    alter a proposal through this payload.
    """

    confirmation_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Identifier returned by the proposal step",
    )
    reason: Optional[str] = Field(
        None, max_length=500, description="Optional note stored with the audit record"
    )
    request_id: Optional[str] = Field(None, description="Optional caller correlation id")


class AttendanceEditConfirmResponse(BaseModel):
    """Result of a successful confirmation."""

    success: bool = Field(..., description="Whether the stored proposal was applied")
    status: str = Field("confirmed", description="Confirmation status")
    confirmation_id: str = Field(..., description="Confirmation identifier that was applied")
    session_id: Optional[str] = Field(None, description="Session that was updated")
    usn: Optional[str] = Field(None, description="Student that was updated")
    old_status: Optional[str] = Field(None, description="Attendance status before the change")
    new_status: Optional[str] = Field(None, description="Attendance status after the change")
    audit_log_id: Optional[int] = Field(None, description="Identifier of the audit record")
    message: str = Field(..., description="Human readable result message")
    request_id: Optional[str] = Field(None, description="Correlation id")

    model_config = ConfigDict(from_attributes=True)
