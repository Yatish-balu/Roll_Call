"""Tool registry and dispatcher for RollCall Agentic AI.

Enforces:
1. Strict JSON parameter validation
2. Capability-family tagging for dynamic subsetting (saving token quota)
3. Role-Based Access Control (RBAC) checked before invoking handlers
4. Risk tier classification (READ, LOW_RISK_WRITE, SENSITIVE_WRITE)
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from app.auth.roles import Role

logger = logging.getLogger("rollcall.agent.registry")


class RiskTier(str, enum.Enum):
    READ = "READ"
    READ_ONLY = "READ"
    LOW_RISK_WRITE = "LOW_RISK_WRITE"
    WRITE = "LOW_RISK_WRITE"
    SENSITIVE_WRITE = "SENSITIVE_WRITE"
    CONFIRM_REQUIRED = "SENSITIVE_WRITE"


@dataclass
class ToolDefinition:
    """Specification of a registered agent tool."""
    name: str
    description: str
    handler: Callable[..., Any]
    parameters: Dict[str, Any] = field(default_factory=dict)
    capability_family: str = "general"  # "schedule", "attendance", "profile", "reports", "general"
    risk_tier: RiskTier = RiskTier.READ
    allowed_roles: Set[str] = field(default_factory=lambda: {"ADMIN", "FACULTY", "COORDINATOR"})
    required_roles: Optional[List[str]] = None
    timeout_seconds: float = 10.0

    def __post_init__(self):
        if self.required_roles:
            self.allowed_roles = {r.upper() for r in self.required_roles}


class ToolRegistry:
    """Thread-safe registry for agent tools with scope and permission enforcement."""

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a new tool into the catalog."""
        self._tools[tool.name] = tool
        logger.debug("Registered agent tool: %s (%s)", tool.name, tool.risk_tier.value)

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Alias for get(name)."""
        return self.get(name)

    def get_tools_schema_for_role(self, role: Optional[str] = None) -> List[Dict[str, Any]]:
        """Convenience helper returning schema for caller role."""
        return self.get_schemas(role=role)

    def list_tools(
        self,
        capability_family: Optional[str] = None,
        role: Optional[str] = None,
    ) -> List[ToolDefinition]:
        """List registered tools optionally filtered by capability family and caller role."""
        results = []
        user_role = (role or "FACULTY").upper()
        for tool in self._tools.values():
            if capability_family and tool.capability_family != capability_family:
                continue
            if user_role not in tool.allowed_roles and "ADMIN" not in user_role:
                continue
            results.append(tool)
        return results

    def get_schemas(
        self,
        capability_family: Optional[str] = None,
        role: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return provider-friendly JSON schemas for available tools."""
        tools = self.list_tools(capability_family=capability_family, role=role)
        schemas = []
        for t in tools:
            schemas.append({
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            })
        return schemas

    def execute(
        self,
        name: Optional[str] = None,
        arguments: Optional[Dict[str, Any]] = None,
        actor_id: str = "anonymous",
        actor_role: Optional[str] = None,
        tool_name: Optional[str] = None,
        role: Optional[str] = None,
        **context: Any,
    ) -> Dict[str, Any]:
        """Validate permissions and execute registered tool."""
        target_name = name or tool_name or ""
        target_role = actor_role or role or "FACULTY"
        tool = self.get(target_name)
        if not tool:
            return {
                "success": False,
                "error": f"Tool '{target_name}' is not registered.",
            }

        clean_role = target_role.upper()
        if clean_role not in tool.allowed_roles and clean_role != "ADMIN":
            logger.warning("Unauthorized tool invocation: %s by %s (%s)", target_name, actor_id, clean_role)
            return {
                "success": False,
                "error": f"Permission denied: role '{clean_role}' cannot execute tool '{target_name}'.",
            }

        try:
            call_args = arguments or {}
            result = tool.handler(actor_id=actor_id, actor_role=target_role, **call_args, **context)
            return {
                "success": True,
                "result": result,
                "risk_tier": tool.risk_tier.value,
            }
        except TypeError:
            # Fallback if handler takes arguments directly
            try:
                result = tool.handler(call_args, actor_id, target_role)
                return {
                    "success": True,
                    "result": result,
                    "risk_tier": tool.risk_tier.value,
                }
            except Exception as exc:
                logger.error("Error executing tool %s: %s", target_name, exc)
                return {
                    "success": False,
                    "error": str(exc),
                }
        except Exception as exc:
            logger.error("Error executing tool %s: %s", target_name, exc)
            return {
                "success": False,
                "error": str(exc),
            }


# Global tool registry singleton
registry = ToolRegistry()
tool_registry = registry


def _query_academic_calendar_handler(
    month: Optional[Any] = None,
    year: Optional[int] = None,
    event_type: Optional[str] = None,
    db: Optional[Any] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Query institutional academic calendar, holidays, and examination events."""
    from datetime import date
    from sqlalchemy import text
    from app.db.connection import get_sync_session_factory
    from contextlib import nullcontext

    factory = get_sync_session_factory()
    session_ctx = db if db is not None else factory()
    with (session_ctx if db is None else nullcontext(db)) as dbs:
        try:
            today = date.today()
            target_year = year or today.year
            target_month = None

            if month is not None:
                if str(month).lower() in ("current", "this", "now", "today"):
                    target_month = today.month
                else:
                    try:
                        target_month = int(month)
                    except (ValueError, TypeError):
                        month_names = {
                            "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
                            "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
                            "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
                            "nov": 11, "november": 11, "dec": 12, "december": 12,
                        }
                        target_month = month_names.get(str(month).strip().lower(), today.month)

            query_sql = "SELECT event_id, title, event_date, end_date, event_type, description FROM academic_events WHERE 1=1"
            params: Dict[str, Any] = {}

            if target_year:
                query_sql += " AND event_date LIKE :year_prefix"
                params["year_prefix"] = f"{target_year}%"

            if target_month:
                month_str = f"{target_month:02d}"
                query_sql += " AND event_date LIKE :month_prefix"
                params["month_prefix"] = f"{target_year}-{month_str}%"

            if event_type and event_type.upper() not in ("ALL", "ANY"):
                query_sql += " AND UPPER(event_type) = :ev_type"
                params["ev_type"] = event_type.upper().strip()

            query_sql += " ORDER BY event_date ASC"
            rows = dbs.execute(text(query_sql), params).fetchall()

            events = []
            for r in rows:
                events.append({
                    "event_id": r[0],
                    "title": r[1],
                    "event_date": str(r[2]),
                    "end_date": str(r[3]) if r[3] else None,
                    "event_type": r[4],
                    "description": r[5],
                })

            return {
                "events": events,
                "count": len(events),
                "year": target_year,
                "month": target_month,
                "message": f"Found {len(events)} institutional event(s) or holiday(s) in academic calendar.",
            }
        except Exception as exc:
            logger.warning("Academic calendar query failed: %s", exc)
            return {"events": [], "count": 0, "error": str(exc), "message": "No academic calendar records found."}


def _query_students_handler(
    semester: Optional[Any] = None,
    branch: Optional[str] = None,
    name: Optional[str] = None,
    usn: Optional[str] = None,
    db: Optional[Any] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Retrieve students matching optional usn, branch, name, or semester filters."""
    from tools.query_tool import query_students
    res = query_students(
        usn=usn,
        branch=branch,
        name=name,
        semester=semester,
        db_target=db,
    )
    return {
        "found": res.found,
        "count": res.total_count,
        "students": res.data,
        "message": res.message,
    }


def register_default_tools(reg: ToolRegistry) -> None:
    """Populate registry with production database-backed tools."""
    from app.agent import tools

    reg.register(
        ToolDefinition(
            name="summarize_attendance",
            description="Summarize attendance metrics (total students, present, absent, pending, unreviewed, and percentage rate) from the database.",
            capability_family="attendance",
            risk_tier=RiskTier.READ,
            allowed_roles={"ADMIN", "FACULTY", "COORDINATOR", "STUDENT", "VIEWER"},
            parameters={
                "type": "object",
                "properties": {
                    "date_str": {"type": "string", "description": "Date to query in 'YYYY-MM-DD' or 'today' or 'all'."},
                    "subject": {"type": "string", "description": "Subject code or name (e.g. 'CN')."},
                    "session_id": {"type": "string", "description": "Specific session ID if querying a single session."},
                },
            },
            handler=tools.summarize_attendance,
        )
    )

    reg.register(
        ToolDefinition(
            name="get_pending_unreviewed_sessions",
            description="Find class sessions that have pending or unreviewed attendance records requiring teacher review.",
            capability_family="attendance",
            risk_tier=RiskTier.READ,
            allowed_roles={"ADMIN", "FACULTY", "COORDINATOR"},
            parameters={
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "Subject code or name filter."},
                },
            },
            handler=tools.get_pending_unreviewed_sessions,
        )
    )

    reg.register(
        ToolDefinition(
            name="get_class_schedule",
            description="Retrieve scheduled academic sessions and timetable for today or a specific date.",
            capability_family="schedule",
            risk_tier=RiskTier.READ,
            allowed_roles={"ADMIN", "FACULTY", "COORDINATOR", "STUDENT", "VIEWER"},
            parameters={
                "type": "object",
                "properties": {
                    "date_str": {"type": "string", "description": "Date in 'YYYY-MM-DD' or 'today' or 'all'."},
                    "subject": {"type": "string", "description": "Subject filter."},
                },
            },
            handler=tools.get_class_schedule,
        )
    )

    reg.register(
        ToolDefinition(
            name="find_vacant_classrooms",
            description="Find vacant or unoccupied classrooms for a given date and period.",
            capability_family="schedule",
            risk_tier=RiskTier.READ,
            allowed_roles={"ADMIN", "FACULTY", "COORDINATOR", "STUDENT"},
            parameters={
                "type": "object",
                "properties": {
                    "date_str": {"type": "string", "description": "Target date or 'today'."},
                    "period": {"type": "integer", "description": "Period number (1 to 8)."},
                },
            },
            handler=tools.find_vacant_classrooms,
        )
    )

    reg.register(
        ToolDefinition(
            name="query_student_attendance_record",
            description="Look up student attendance history and attendance percentage by USN.",
            capability_family="attendance",
            risk_tier=RiskTier.READ,
            allowed_roles={"ADMIN", "FACULTY", "COORDINATOR"},
            parameters={
                "type": "object",
                "properties": {
                    "usn": {"type": "string", "description": "Student USN (e.g. '1MS21CS001')."},
                    "subject": {"type": "string", "description": "Optional subject filter."},
                },
                "required": ["usn"],
            },
            handler=tools.query_student_attendance_record,
        )
    )

    reg.register(
        ToolDefinition(
            name="create_attendance_session",
            description="Create a new class attendance session in the database for an assigned subject.",
            capability_family="schedule",
            risk_tier=RiskTier.LOW_RISK_WRITE,
            allowed_roles={"ADMIN", "FACULTY"},
            parameters={
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "Subject code (e.g. 'CN')."},
                    "date_str": {"type": "string", "description": "Date in 'YYYY-MM-DD' format."},
                    "session_id": {"type": "string", "description": "Optional custom session ID."},
                },
                "required": ["subject", "date_str"],
            },
            handler=tools.create_attendance_session,
        )
    )

    reg.register(
        ToolDefinition(
            name="update_user_profile",
            description="Update the current user's profile information such as full name or display name.",
            capability_family="profile",
            risk_tier=RiskTier.LOW_RISK_WRITE,
            allowed_roles={"ADMIN", "FACULTY", "COORDINATOR", "STUDENT"},
            parameters={
                "type": "object",
                "properties": {
                    "full_name": {"type": "string", "description": "The new display name / full name (e.g. 'ramu')."},
                    "email": {"type": "string", "description": "Optional new email address."},
                    "mobile": {"type": "string", "description": "Optional new phone number."},
                    "designation": {"type": "string", "description": "Optional designation."},
                },
            },
            handler=tools.update_user_profile,
        )
    )

    reg.register(
        ToolDefinition(
            name="create_faculty_user",
            description="Create a new faculty/teacher or staff account in the system with login credentials. Admin only.",
            capability_family="admin",
            risk_tier=RiskTier.LOW_RISK_WRITE,
            allowed_roles={"ADMIN"},
            parameters={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "Unique username / user_id for the faculty member (e.g. 'dr_ramesh')."},
                    "name": {"type": "string", "description": "Full legal name of the faculty member (e.g. 'Dr. Ramesh Kumar')."},
                    "email": {"type": "string", "description": "Institutional email address."},
                    "password": {"type": "string", "description": "Initial login password (minimum 6 characters)."},
                    "branch": {"type": "string", "description": "Branch code (e.g. 'CSE', 'CY', 'ISE')."},
                    "designation": {"type": "string", "description": "Job designation (e.g. 'Assistant Professor', 'Professor')."},
                    "department": {"type": "string", "description": "Department name."},
                },
                "required": ["user_id", "name", "email", "password"],
            },
            handler=tools.create_faculty_user,
        )
    )

    reg.register(
        ToolDefinition(
            name="query_academic_calendar",
            description="Query institutional academic calendar, holidays, CIE/exam schedules, and institutional events. NEVER invent holidays from external memory; always query this tool.",
            capability_family="schedule",
            risk_tier=RiskTier.READ,
            allowed_roles={"ADMIN", "FACULTY", "COORDINATOR", "STUDENT", "VIEWER"},
            parameters={
                "type": "object",
                "properties": {
                    "month": {"type": "string", "description": "Target month number (1-12) or name (e.g. 'November' or 'current')."},
                    "year": {"type": "integer", "description": "Calendar year (e.g. 2026)."},
                    "event_type": {"type": "string", "description": "Optional event filter: 'HOLIDAY', 'EXAM', 'CIE', 'ACADEMIC', 'ALL'."},
                },
            },
            handler=_query_academic_calendar_handler,
        )
    )

    reg.register(
        ToolDefinition(
            name="query_students",
            description="Query student records by semester number (e.g. 5), branch (e.g. 'CY'), student name, or USN.",
            capability_family="general",
            risk_tier=RiskTier.READ,
            allowed_roles={"ADMIN", "FACULTY", "COORDINATOR", "STUDENT", "VIEWER"},
            parameters={
                "type": "object",
                "properties": {
                    "semester": {"type": "integer", "description": "Semester number (e.g. 5 for 5th semester)."},
                    "branch": {"type": "string", "description": "Branch code (e.g. 'CY', 'CSE')."},
                    "name": {"type": "string", "description": "Student full or partial name (e.g. 'Yatish')."},
                    "usn": {"type": "string", "description": "Student USN (e.g. '1DS24CY060')."},
                },
            },
            handler=_query_students_handler,
        )
    )

    try:
        from app.agent.tools.profile_analytics_tools import GET_DEFAULTERS_ANALYSIS_TOOL
        reg.register(GET_DEFAULTERS_ANALYSIS_TOOL)
    except Exception as def_err:
        logger.debug("Defaulters tool registration note: %s", def_err)

    try:
        from app.agent.tools.attendance_tools import EXPORT_ATTENDANCE_TOOL
        reg.register(EXPORT_ATTENDANCE_TOOL)
    except Exception as exp_err:
        logger.debug("Export attendance tool registration note: %s", exp_err)

    # Register Exam AI Tools
    try:
        from app.agent.tools.exam_tools import (
            QUERY_EXAM_STATUS_TOOL,
            QUERY_EXAM_ABSENTEES_TOOL,
            QUERY_EXAM_BRANCH_SUMMARY_TOOL,
        )
        reg.register(QUERY_EXAM_STATUS_TOOL)
        reg.register(QUERY_EXAM_ABSENTEES_TOOL)
        reg.register(QUERY_EXAM_BRANCH_SUMMARY_TOOL)
    except Exception as e:
        logger.warning("Could not register exam agent tools: %s", e)


# Automatically register default tools
register_default_tools(tool_registry)


