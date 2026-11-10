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
    query: str = Field(..., min_length=1, description="Question about attendance, records, or students")
    session_id: Optional[str] = Field(None, description="Optional target session filter")


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

