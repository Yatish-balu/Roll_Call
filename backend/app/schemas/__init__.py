"""RollCall API Pydantic v2 schemas package."""

from app.schemas.student import (
    StudentBase,
    StudentCreate,
    StudentUpdate,
    StudentResponse,
    StudentPageResponse,
    StudentBulkCreate,
)
from app.schemas.room import (
    RoomBase,
    RoomCreate,
    RoomUpdate,
    RoomResponse,
    RoomPageResponse,
    RoomBulkCreate,
)
from app.schemas.session import (
    SessionBase,
    SessionCreate,
    SessionUpdate,
    SessionResponse,
    SessionPageResponse,
    SessionBulkCreate,
)
from app.schemas.attendance import (
    AttendanceBase,
    AttendanceCreate,
    AttendanceUpdate,
    AttendanceResponse,
    AttendanceDetailResponse,
    AttendanceBulkCreate,
    ReconcileRequest,
    BulkReconcileRequest,
    SessionReconcilePayload,
    AttendanceStatusLiteral,
    ALLOWED_STATUSES,
)
from app.schemas.analytics import (
    GroupSummaryBase,
    RoomWiseSummary,
    BranchWiseSummary,
    OverallSummary,
    SummaryReportResponse,
    ExportReportRequest,
)
from app.schemas.agent import (
    ToolCallLogSchema,
    ConfirmationRequestSchema,
    AgentRequest,
    ChatQueryRequest,
    FileUploadResponse,
    AgentResponseSchema,
    AgentConfirmRequest,
    AgentStatusResponse,
)
from app.schemas.auth import (
    Role,
    TokenPayload,
    AuthenticatedUser,
)

__all__ = [
    # Student
    "StudentBase",
    "StudentCreate",
    "StudentUpdate",
    "StudentResponse",
    "StudentPageResponse",
    "StudentBulkCreate",
    # Room
    "RoomBase",
    "RoomCreate",
    "RoomUpdate",
    "RoomResponse",
    "RoomPageResponse",
    "RoomBulkCreate",
    # Session
    "SessionBase",
    "SessionCreate",
    "SessionUpdate",
    "SessionResponse",
    "SessionPageResponse",
    "SessionBulkCreate",
    # Attendance
    "AttendanceBase",
    "AttendanceCreate",
    "AttendanceUpdate",
    "AttendanceResponse",
    "AttendanceDetailResponse",
    "AttendanceBulkCreate",
    "ReconcileRequest",
    "BulkReconcileRequest",
    "SessionReconcilePayload",
    "AttendanceStatusLiteral",
    "ALLOWED_STATUSES",
    # Analytics
    "GroupSummaryBase",
    "RoomWiseSummary",
    "BranchWiseSummary",
    "OverallSummary",
    "SummaryReportResponse",
    "ExportReportRequest",
    # Agent
    "ToolCallLogSchema",
    "ConfirmationRequestSchema",
    "AgentRequest",
    "ChatQueryRequest",
    "FileUploadResponse",
    "AgentResponseSchema",
    "AgentConfirmRequest",
    "AgentStatusResponse",
    # Auth
    "Role",
    "TokenPayload",
    "AuthenticatedUser",
]

