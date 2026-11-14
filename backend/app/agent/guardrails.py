"""Input guardrails, tool-scope enforcement, and output sanitization for RollCall AI Agent.

Provides three defensive layers used by the agentic loop:

1. :class:`PromptInjectionGuard` - scans raw user input for injection attempts
   before it reaches the LLM.
2. :class:`ScopeGuard` - enforces subject-scoped RBAC before agent tools run.
3. :class:`OutputSanitizer` - masks secrets (JWTs, passwords, connection strings,
   system secrets) in agent output before it reaches the frontend/user.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


class PromptInjectionGuard:
    """Detects prompt-injection attempts in user-supplied input."""

    # Regexes matching common injection payloads (matched case-insensitively).
    INJECTION_PATTERNS: List[str] = [
        r"ignore\s+(?:previous\s+)?(?:instructions|system\s+prompt|directives?)",
        r"disregard\s+(?:previous\s+)?(?:instructions|rules|guidelines)",
        r"drop\s+table",
        r"system\s+override",
        r"bypass\s+(?:auth|authentication|authorization)",
        r"you\s+are\s+now\s+(?:a|an)\s+",
        r"jailbreak",
        r"prompt\s+injection",
        r"\bsudo\b",
        r"rm\s+-rf\s+/",
        r";\s*drop\s+table",
    ]

    def validate_input(self, prompt: str) -> Tuple[bool, str]:
        """Return ``(is_safe, reason)`` for the given user prompt.

        A prompt is unsafe when it matches any known injection pattern. Safe
        prompts return ``(True, "")``.
        """
        text = prompt or ""
        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return False, f"Blocked potential prompt injection (matched: {pattern})"
        return True, ""


class ScopeGuard:
    """Enforces subject-scoped RBAC before agent tools are executed.

    Rules:
    * ``ADMIN`` is unrestricted.
    * ``FACULTY`` may only act on subjects listed in ``assigned_subjects``.
    * ``STUDENT`` / ``VIEWER`` cannot execute sensitive (write) tools.
    """

    SENSITIVE_TOOLS: frozenset = frozenset({
        "create_session",
        "edit_session",
        "update_session",
        "delete_session",
        "mark_attendance",
        "update_attendance",
        "bulk_update_attendance",
        "create_student",
        "edit_student",
        "delete_student",
    })

    SUBJECT_ARG_KEYS: frozenset = frozenset({
        "subject_id",
        "subject_code",
        "subject",
        "course_id",
        "course_code",
        "class_id",
        "session_subject_id",
    })

    def validate_tool_scope(
        self,
        tool_name: str,
        args: dict,
        actor_id: str,
        role: str,
        assigned_subjects: list[str],
    ) -> Tuple[bool, str]:
        """Return ``(is_safe, reason)`` for a proposed tool execution.

        ``actor_id`` is included in rejection reasons for audit traceability.
        """
        clean_role = (role or "").upper()
        tool = (tool_name or "").lower()
        arguments = args or {}
        subjects = [str(s).upper() for s in (assigned_subjects or [])]

        # 1. Admin is unrestricted.
        if clean_role == "ADMIN":
            return True, ""

        # 2. Students / viewers cannot run sensitive write tools.
        if clean_role in {"STUDENT", "VIEWER"} and tool in self.SENSITIVE_TOOLS:
            return (
                False,
                f"Role '{clean_role}' is not permitted to execute sensitive tool '{tool_name}'.",
            )

        # 3. Faculty may only act on their assigned subjects.
        if clean_role == "FACULTY":
            subject_value = self._extract_subject(arguments)
            if subject_value is not None and subject_value.upper() not in subjects:
                return (
                    False,
                    f"Actor '{actor_id}' (FACULTY) is not assigned to subject "
                    f"'{subject_value}'; assigned subjects: {subjects or 'none'}.",
                )

        return True, ""

    @staticmethod
    def _extract_subject(args: Dict[str, Any]) -> str | None:
        """Pull a subject identifier out of tool arguments, recursing into dicts."""
        for key in ScopeGuard.SUBJECT_ARG_KEYS:
            if key in args and args[key] not in (None, ""):
                return str(args[key])
        for value in args.values():
            if isinstance(value, dict):
                nested = ScopeGuard._extract_subject(value)
                if nested is not None:
                    return nested
        return None


class OutputSanitizer:
    """Masks sensitive material in agent output before it reaches the user."""

    # JWT: three base64url-ish segments separated by dots.
    JWT_PATTERN = re.compile(r"\b[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
    # Common database connection string schemes.
    CONNECTION_STRING_PATTERNS: List[re.Pattern] = [
        re.compile(r"(?i)\b(postgres(?:ql)?://|mysql://|mongodb://|redis://|sqlite:///|mssql://|oracle://)[^\s]+"),
    ]
    # key=value / key: value secret disclosures.
    SECRET_KV_PATTERNS: List[re.Pattern] = [
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|apikey|token|access[_-]?token|private[_-]?key)\s*[:=]\s*([^\s,;}]+)"
        ),
    ]

    def sanitize_output(self, text: str) -> str:
        """Return ``text`` with JWTs, passwords, connection strings, and secrets masked."""
        masked = text or ""
        masked = self.JWT_PATTERN.sub("[REDACTED_JWT]", masked)
        for pattern in self.CONNECTION_STRING_PATTERNS:
            masked = pattern.sub("[REDACTED_CONNECTION_STRING]", masked)
        for pattern in self.SECRET_KV_PATTERNS:
            masked = pattern.sub(lambda m: f"{m.group(1)}=[REDACTED]", masked)
        return masked
