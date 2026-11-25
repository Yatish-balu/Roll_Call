"""Input guardrails, tool-scope enforcement, and output sanitization for RollCall AI Agent.

Provides four defensive layers used by the agentic loop:

1. :class:`PromptInjectionGuard` - scans raw user input for injection attempts
   before it reaches the LLM.
2. :class:`ScopeGuard` - enforces subject-scoped RBAC before agent tools run.
3. :class:`OutputSanitizer` - masks secrets (JWTs, passwords, connection strings,
   system secrets) in agent output before it reaches the frontend/user.
4. :func:`validate_agent_output` - blocks system-prompt/internal-policy
   leakage and obvious off-topic drift before the response is returned.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel

from app.agent.gatekeeper import (
    GATEKEEPER_DOMAIN_REFUSAL,
    GATEKEEPER_SECURITY_REFUSAL,
    GatekeeperDecision,
)


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
        # System-prompt extraction and persona hijacking.
        r"(?:reveal|show|print|repeat|dump|leak|output)\s+(?:me\s+)?(?:your|the)\s+"
        r"(?:system\s+prompt|hidden\s+prompt|instructions?|developer\s+message)",
        r"(?:pretend|roleplay|imagine)\s+(?:that\s+)?(?:you(?:'re|\s+are)|to\s+be)\s+"
        r"(?:an?\s+)?[\s\S]{0,60}?"
        r"(?:professor|teacher|tutor|expert|assistant|admin(?:istrator)?|root|"
        r"superuser|developer|system|unrestricted|dan)",
        r"(?:from\s+now\s+on[,\s]+(?:you\s+are|you're|act\s+as)|you\s+are\s+now)\s+"
        r"(?:an?\s+)?[\s\S]{0,50}?"
        r"(?:professor|teacher|tutor|expert|assistant|admin|root|system|"
        r"unrestricted|dan)",
        # Delimiter escapes that try to close a data block early.
        r"<\s*/?\s*(?:user_query|uploaded_document|untrusted_content|"
        r"system_prompt|system|assistant|developer)\s*>",
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


# ---------------------------------------------------------------------------
# Post-generation output guard
# ---------------------------------------------------------------------------


class OutputCheckResult(BaseModel):
    """Verdict returned by :func:`validate_agent_output`."""

    allowed: bool
    sanitized_response: str
    blocked_reason: Optional[str] = None


#: Text that only exists in the server-side system prompt.  Seeing it in a
#: response means the model leaked its instructions.
_SYSTEM_PROMPT_MARKERS: Tuple[str, ...] = (
    "OPERATIONAL SCOPE & STRICT DOMAIN BOUNDARY",
    "STRICT OUT-OF-DOMAIN REFUSAL POLICY",
    "SPEED & EFFICIENCY DIRECTIVES",
    "LOGGED-IN TEACHER PROFILE & LIVE ACADEMIC SNAPSHOT",
    "You are Antigravity RollCall AI",
    "system_instruction",
    "hidden prompt",
    "developer message",
    "my instructions are",
)

#: Text that exposes internal implementation/policy details.
_INTERNAL_POLICY_MARKERS: Tuple[str, ...] = (
    "TOOL_POLICIES",
    "TOOL_MINIMUM_ROLE",
    "TRUSTED_INTERNAL",
    "LimitScope",
    "PromptInjectionGuard",
    "ScopeGuard",
    "OutputSanitizer",
    "GEMINI_API_KEY",
    "JWT_SECRET",
    "SEC_ADMIN_KEY",
    "DATABASE_URL",
    "admin_key",
)

#: A refusal that mentions a prompt/policy word is not a leak.
_LEAK_REFUSAL_CONTEXT = re.compile(
    r"\b(?:can't|cannot|can\s+not|won't|will\s+not|unable|not\s+able|not\s+allowed|"
    r"sorry|refuse|don't|do\s+not)\b[\s\S]{0,80}"
    r"\b(?:system\s+prompt|instructions?|internal|policy|secret|prompt|credentials?)\b",
    re.IGNORECASE,
)

#: High-confidence off-topic answer shapes, used only when no gatekeeper verdict
#: is supplied and no tool produced the content.
_OFF_TOPIC_ANSWER_RE = re.compile(
    r"\b(?:ingredients?|preheat|simmer|boil|recipe)\b|"
    r"\b(?:once\s+upon\s+a\s+time|roses\s+are\s+red|here'?s\s+a\s+poem)\b|"
    r"\b(?:the\s+capital\s+of|prime\s+minister\s+of|quantum\s+(?:computing|mechanics)|"
    r"binary\s+search\s+(?:works|algorithm))\b",
    re.IGNORECASE,
)

_DOMAIN_REFUSAL_CORE = "specialized exclusively for institutional attendance"
_SECURITY_REFUSAL_CORE = "can't help with requests that try to change my instructions"


def _decision_value(decision: Optional[Any]) -> str:
    if decision is None:
        return ""
    if isinstance(decision, str):
        return decision.strip().upper()
    value = getattr(decision, "decision", None)
    if value is None and isinstance(decision, dict):
        value = decision.get("decision")
    return str(value or "").strip().upper()


def _is_domain_refusal(text: str) -> bool:
    return _DOMAIN_REFUSAL_CORE in (text or "").lower()


def _is_security_refusal(text: str) -> bool:
    return _SECURITY_REFUSAL_CORE in (text or "").lower()


def _detect_leak(text: str) -> Optional[str]:
    lower = (text or "").lower()
    for marker in _SYSTEM_PROMPT_MARKERS:
        if marker.lower() in lower:
            return "system_prompt_leakage"
    for marker in _INTERNAL_POLICY_MARKERS:
        if marker.lower() in lower:
            # "I cannot share internal policy" is a safe refusal, not a leak.
            if _LEAK_REFUSAL_CONTEXT.search(text or ""):
                continue
            return "internal_policy_leakage"
    # A refusal that names the system prompt is safe; an answer that quotes it
    # is not.
    if "system prompt" in lower and not _LEAK_REFUSAL_CONTEXT.search(text or ""):
        return "system_prompt_leakage"
    return None


def validate_agent_output(
    response_text: str,
    *,
    tool_called: bool,
    gatekeeper_decision: Optional[GatekeeperDecision] = None,
) -> OutputCheckResult:
    """Final guard applied to model output before it reaches the user.

    Blocks system-prompt/internal-policy leakage and obvious off-topic drift.
    Secrets are always redacted, even when the response is allowed.
    """

    sanitizer = OutputSanitizer()
    sanitized = sanitizer.sanitize_output(response_text or "")
    decision = _decision_value(gatekeeper_decision)

    leak = _detect_leak(sanitized)
    if leak is not None:
        return OutputCheckResult(
            allowed=False,
            sanitized_response=GATEKEEPER_SECURITY_REFUSAL,
            blocked_reason=leak,
        )

    if decision == "PROMPT_INJECTION":
        if _is_security_refusal(sanitized):
            return OutputCheckResult(allowed=True, sanitized_response=sanitized)
        return OutputCheckResult(
            allowed=False,
            sanitized_response=GATEKEEPER_SECURITY_REFUSAL,
            blocked_reason="prompt_injection_response",
        )

    if decision == "OUT_OF_SCOPE":
        if _is_domain_refusal(sanitized):
            return OutputCheckResult(allowed=True, sanitized_response=sanitized)
        return OutputCheckResult(
            allowed=False,
            sanitized_response=GATEKEEPER_DOMAIN_REFUSAL,
            blocked_reason="off_topic_drift",
        )

    # No explicit gatekeeper verdict: refuse high-confidence off-topic answers
    # that were not grounded in a tool result.
    if not tool_called and _OFF_TOPIC_ANSWER_RE.search(sanitized):
        return OutputCheckResult(
            allowed=False,
            sanitized_response=GATEKEEPER_DOMAIN_REFUSAL,
            blocked_reason="off_topic_drift",
        )

    return OutputCheckResult(allowed=True, sanitized_response=sanitized)


__all__ = [
    "OutputCheckResult",
    "OutputSanitizer",
    "PromptInjectionGuard",
    "ScopeGuard",
    "validate_agent_output",
]
