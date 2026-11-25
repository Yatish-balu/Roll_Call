"""Server-side authorization policy for AI tools.

The backend is the authorization authority for every AI tool call. The model
may *select* a tool, but it can never widen the caller's permissions: the
registry consults this policy before a handler runs, using the role that came
from the verified authentication context.

This is defense in depth. Route-level dependencies (``require_roles``) remain
the primary control; this policy ensures a future/alternate call path cannot
skip it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Final, FrozenSet, Optional, Union

from app.auth.roles import role_satisfies
from app.schemas.auth import Role


class ToolAuthorizationError(PermissionError):
    """Raised when an actor attempts to execute a tool above their role."""


ToolAccessDenied = ToolAuthorizationError


class _TrustedInternalExecution:
    """Opaque capability for explicitly trusted, non-user initiated jobs."""


TRUSTED_INTERNAL: Final = _TrustedInternalExecution()


@dataclass(frozen=True)
class ToolPolicy:
    """Minimum role required to execute one registered AI tool."""

    tool_name: str
    required_role: Role
    reason: str


#: Minimum role per AI tool. ADMIN inherits FACULTY, FACULTY inherits VIEWER.
TOOL_POLICIES: Dict[str, ToolPolicy] = {
    "read_csv_tool": ToolPolicy(
        "read_csv_tool", Role.FACULTY, "parses uploaded attendance data"
    ),
    "read_photo_tool": ToolPolicy(
        "read_photo_tool", Role.FACULTY, "runs OCR over uploaded attendance images"
    ),
    "validate_tool": ToolPolicy(
        "validate_tool", Role.FACULTY, "processes attendance records"
    ),
    "summary_tool": ToolPolicy(
        "summary_tool", Role.FACULTY, "aggregates attendance into reports"
    ),
    "export_tool": ToolPolicy(
        "export_tool", Role.FACULTY, "writes report files"
    ),
    "query_tool": ToolPolicy(
        "query_tool", Role.VIEWER, "read-only attendance queries"
    ),
}

TOOL_MINIMUM_ROLE: Dict[str, Role] = {
    name: policy.required_role for name, policy in TOOL_POLICIES.items()
}


def required_role_for_tool(tool_name: str) -> Optional[Role]:
    """Return the minimum role for *tool_name* (``None`` for unknown tools)."""
    policy = TOOL_POLICIES.get(tool_name)
    return policy.required_role if policy else None


def authorize_tool(tool_name: str, actor_role: Union[Role, str, _TrustedInternalExecution, None]) -> None:
    """Raise :class:`ToolAuthorizationError` when *actor_role* may not run *tool_name*.

    Unknown tools are left to the registry's "unknown tool" handling so the
    caller gets a consistent error. Missing or invalid roles are treated as
    VIEWER. Trusted internal jobs must pass the opaque sentinel explicitly.
    """
    policy = TOOL_POLICIES.get(tool_name)
    if policy is None:
        return

    if actor_role is TRUSTED_INTERNAL:
        return

    if isinstance(actor_role, Role):
        role = actor_role
    elif actor_role is None:
        role = Role.VIEWER
    else:
        try:
            role = Role(str(actor_role).strip().upper())
        except ValueError:
            role = Role.VIEWER

    if not role_satisfies(role, policy.required_role):
        raise ToolAuthorizationError(
            f"Forbidden: role '{role.value}' may not execute AI tool "
            f"'{tool_name}' (requires '{policy.required_role.value}')."
        )


def require_tool_access(tool_name: str, role: Optional[Union[Role, str, _TrustedInternalExecution]]) -> None:
    """Compatibility alias for authorize_tool."""
    policy = TOOL_POLICIES.get(tool_name)
    if policy is None:
        raise ToolAuthorizationError(f"Tool '{tool_name}' is not recognized or permitted.")
    authorize_tool(tool_name, role)


def allowed_tools(role: Optional[Role]) -> FrozenSet[str]:
    """Return the tool names callable by ``role`` (``None`` means unrestricted)."""
    if role is None:
        return frozenset(TOOL_MINIMUM_ROLE)
    return frozenset(
        name for name, min_role in TOOL_MINIMUM_ROLE.items()
        if role_satisfies(role, min_role)
    )


def tool_permission_matrix() -> Dict[str, str]:
    """Role matrix for documentation/status endpoints (no secrets)."""
    return {name: policy.required_role.value for name, policy in TOOL_POLICIES.items()}


# ---------------------------------------------------------------------------
# Domain-scope policy
# ---------------------------------------------------------------------------
#
# A subject code is permission to read or change *data about that subject*.  It
# is not permission to tutor the subject.  For example, "show DDCO attendance"
# is an academic operation, while "explain DDCO basics" is general tutoring and
# must not be whitelisted merely because "DDCO" appears in the text.

#: Terms that unambiguously describe a RollCall data operation.
ACADEMIC_OPERATION_TERMS: FrozenSet[str] = frozenset(
    {
        "attendance",
        "absent",
        "absentee",
        "absentees",
        "defaulter",
        "defaulters",
        "shortage",
        "timetable",
        "schedule",
        "session",
        "sessions",
        "roster",
        "usn",
        "semester",
        "branch",
        "invigilation",
        "seating",
        "vacant",
        "classroom",
        "audit log",
        "pending review",
        "assigned subject",
        "student record",
        "student directory",
        "cie",
        "academic calendar",
        "room allocation",
        "exam room",
        "exam allocation",
        "department",
        "dept",
        "subject",
        "profile",
        "display name",
    }
)

_ACADEMIC_OPERATION_RE = re.compile(
    r"\b(?:attendance|absent(?:ee)?s?|defaulter(?:s)?|shortage|timetable|time\s+table|"
    r"schedule|session(?:s)?|roster|usn|semester|branch|invigilat\w*|seating|vacant|"
    r"classroom|audit\s+logs?|pending\s+reviews?|assigned\s+subjects?|"
    r"student\s+records?|student\s+directory|cie|academic\s+calendar|"
    r"room\s+allocation|exam\s+room|exam\s+allocation)\b",
    re.IGNORECASE,
)

#: Directory nouns that are academic only when qualified by an owning/data verb.
#: This keeps "show all departments" in scope without whitelisting
#: "explain the subject of quantum computing" or "profile of the prime minister".
_WEAK_ACADEMIC_RE = re.compile(
    r"\b(?:my|our|faculty|teacher|student)\s+(?:profile|profiles|subjects?|department|dept)\b|"
    r"\b(?:show|list|display|view|get|all|assigned)\b[\s\S]{0,20}"
    r"\b(?:departments?|dept|subjects?|profiles?)\b|"
    r"\b(?:what|which)\s+subjects?\s+(?:do|am|have|are)\b|"
    r"\bwho\s+is\s+the\s+(?:hod|head|dean|faculty|professor|teacher)\b|"
    r"\bdisplay\s+name\b",
    re.IGNORECASE,
)

_PRESENT_RE = re.compile(
    r"\b(?:students?|class|attendance)\b[\s\S]{0,40}\b(?:present|absent)\b|"
    r"\b(?:present|absent)\b[\s\S]{0,40}\b(?:students?|class)\b",
    re.IGNORECASE,
)

_STUDENT_DATA_RE = re.compile(
    r"\b(?:show|list|display|find|get|count|how\s+many|which|all|search)\b"
    r"[\s\S]{0,40}\b(?:students?|usns?|rosters?)\b|"
    r"\b(?:students?|usns?|rosters?)\b[\s\S]{0,40}"
    r"\b(?:list|records?|details?|count|present|absent)\b",
    re.IGNORECASE,
)

#: Natural-language schedule questions: "my next class", "today's lectures".
_SCHEDULE_CLASS_RE = re.compile(
    r"\b(?:my\s+)?(?:next|first|last|today'?s?|tomorrow'?s?|current)\s+"
    r"(?:class|classes|lecture|lectures|period|periods?|session|sessions?)\b|"
    r"\bmy\s+(?:class|classes|lectures?|periods?|schedule|timetable)\b",
    re.IGNORECASE,
)

#: Room availability questions: "Is room LH-101 available?", "any free rooms".
_ROOM_QUERY_RE = re.compile(
    r"\broom\s+(?:id\s+)?[a-z]{0,4}[-\s]?\d{1,4}\b|"
    r"\b(?:available|vacant|free|occupied|booked|empty)\b[\s\S]{0,20}\brooms?\b|"
    r"\brooms?\b[\s\S]{0,20}\b(?:available|vacant|free|occupied|booked|empty)\b",
    re.IGNORECASE,
)

_HOLIDAY_RE = re.compile(r"\bholiday(?:s)?\b", re.IGNORECASE)
_HOLIDAY_CONTEXT_RE = re.compile(
    r"\b(?:this|current|next|last|upcoming)\s+(?:month|week|year)\b|"
    r"\b(?:calendar|academic|list|count|how\s+many|when|dates?|schedule)\b",
    re.IGNORECASE,
)
_CALENDAR_OPERATION_RE = re.compile(
    r"\b(?:academic\s+calendar|calendar\s+events?|holiday\s+calendar|"
    r"upcoming\s+events?|college\s+events?)\b",
    re.IGNORECASE,
)

#: Subject names that also occur in general-knowledge questions.
SUBJECT_NAME_COLLISIONS: FrozenSet[str] = frozenset(
    {
        "ddco",
        "dbms",
        "os",
        "cn",
        "ai",
        "ml",
        "se",
        "ecs",
        "rm",
        "web-tech",
        "web tech",
        "digital design",
        "computer organization",
        "microprocessor",
        "operating system",
        "operating systems",
        "computer networks",
        "data structures",
        "algorithms",
        "software engineering",
        "machine learning",
        "artificial intelligence",
        "cloud computing",
        "computer graphics",
        "discrete mathematics",
        "compiler",
        "automata",
    }
)

_SUBJECT_COLLISION_RE = re.compile(
    r"\b(?:ddco|dbms|os|cn|ai|ml|se|ecs|rm|web[- ]?tech|digital\s+design|"
    r"computer\s+organization|microprocessor|operating\s+systems?|"
    r"computer\s+networks?|data\s+structures?|algorithms?|software\s+engineering|"
    r"machine\s+learning|artificial\s+intelligence|cloud\s+computing|"
    r"computer\s+graphics|discrete\s+mathematics|compiler|automata)\b",
    re.IGNORECASE,
)

_TUTORING_RE = re.compile(
    r"\b(?:explain|xplain|describe|define|teach(?:\s+me)?|"
    r"what\s+(?:is|are)|basics?|fundamentals?|introduction\s+to|concept\s+of|"
    r"difference\s+between|how\s+(?:does|do|to\s+(?:make|cook|write|code|solve))|"
    r"why\s+(?:does|do|is|are))\b",
    re.IGNORECASE,
)

_GENERAL_KNOWLEDGE_RE = re.compile(
    r"\b(?:prime\s+minister|president|capital\s+of|recipe|restaurant|poem|joke|"
    r"quantum|physics|chemistry|diwali|festival|movie|cricket|history\s+of)\b",
    re.IGNORECASE,
)


def has_academic_operation(text: str) -> bool:
    """Return ``True`` when *text* asks for a RollCall data operation.

    A holiday question counts only when it is anchored to a calendar context
    (month/week/year, count, list, calendar) - never when it is a general
    knowledge question such as "what is a holiday".
    """

    clean = (text or "").strip()
    if not clean:
        return False
    if _ACADEMIC_OPERATION_RE.search(clean):
        return True
    if _WEAK_ACADEMIC_RE.search(clean):
        return True
    if _PRESENT_RE.search(clean):
        return True
    if _STUDENT_DATA_RE.search(clean):
        return True
    if _SCHEDULE_CLASS_RE.search(clean):
        return True
    if _ROOM_QUERY_RE.search(clean):
        return True
    if _HOLIDAY_RE.search(clean) and _HOLIDAY_CONTEXT_RE.search(clean):
        return True
    if _CALENDAR_OPERATION_RE.search(clean):
        return True
    return False


def mentions_subject_name(text: str) -> bool:
    """Return ``True`` when a real course/subject name appears in *text*."""

    return bool(_SUBJECT_COLLISION_RE.search(text or ""))


def is_tutoring_request(text: str) -> bool:
    """Return ``True`` for explain/define/teach-style requests."""

    return bool(_TUTORING_RE.search(text or ""))


def is_subject_tutoring_request(text: str) -> bool:
    """A subject mention combined with a teaching request, but no data operation.

    This is the DDCO rule: "explain DDCO basics" is tutoring, whereas
    "show DDCO attendance" is an academic operation.
    """

    clean = text or ""
    return (
        mentions_subject_name(clean)
        and is_tutoring_request(clean)
        and not has_academic_operation(clean)
    )


def subject_collision_allows_request(text: str) -> bool:
    """Whether a subject-name collision grants access to a RollCall operation.

    The answer is ``True`` only when the message actually asks for institutional
    data.  A bare subject mention never authorizes general tutoring.
    """

    return has_academic_operation(text)


def is_general_knowledge_question(text: str) -> bool:
    """``True`` for general-knowledge/trivia text with no academic operation."""

    clean = text or ""
    return bool(_GENERAL_KNOWLEDGE_RE.search(clean)) and not has_academic_operation(clean)


__all__ = [
    "ACADEMIC_OPERATION_TERMS",
    "SUBJECT_NAME_COLLISIONS",
    "ToolAuthorizationError",
    "ToolAccessDenied",
    "TRUSTED_INTERNAL",
    "allowed_tools",
    "authorize_tool",
    "has_academic_operation",
    "is_general_knowledge_question",
    "is_subject_tutoring_request",
    "is_tutoring_request",
    "mentions_subject_name",
    "require_tool_access",
    "required_role_for_tool",
    "subject_collision_allows_request",
    "tool_permission_matrix",
]
