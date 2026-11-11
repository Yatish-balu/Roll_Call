"""Prompt-injection screening for the AI agent input.

The model is never the authorization boundary - data scope and SQL policy are
enforced in code - but untrusted text can still steer *what* the agent answers
and which tools it reaches for. This module screens user-supplied text before
it is handed to the agent and fails closed on known instruction-hijacking and
secret-exfiltration patterns.

File contents are data, never instructions: they are parsed by the tools, not
appended to a prompt. Only the chat text (and the session id echoed into it) is
screened.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Pattern, Tuple

# Long natural-language requests are legitimate; wall-of-text prompts are not.
MAX_AGENT_INPUT_CHARS = 4000


class PromptInjectionError(ValueError):
    """Raised when agent input matches a prompt-injection pattern."""

    def __init__(self, pattern: str) -> None:
        self.pattern = pattern
        super().__init__(
            "The request was rejected because it looks like an attempt to "
            "override the assistant's instructions. Ask a normal attendance "
            "question instead."
        )


@dataclass(frozen=True)
class InjectionPattern:
    name: str
    regex: Pattern[str]


_PATTERNS: Tuple[InjectionPattern, ...] = (
    InjectionPattern(
        "instruction_override",
        re.compile(
            r"\b(ignore|disregard|forget|bypass|override)\b[\s\S]{0,60}?"
            r"\b(previous|prior|above|earlier|all|any)\b[\s\S]{0,30}?"
            r"\b(instruction|instructions|prompt|prompts|rule|rules|direction|directions|context)\b",
            re.IGNORECASE,
        ),
    ),
    InjectionPattern(
        "system_prompt_probe",
        re.compile(
            r"\b(system|developer|hidden|initial)\s+(prompt|message|instructions?)\b",
            re.IGNORECASE,
        ),
    ),
    InjectionPattern(
        "role_hijack",
        re.compile(
            r"\b(you are now|from now on,? you|act as|pretend to be|behave as)\b"
            r"[\s\S]{0,50}?\b(admin|administrator|root|developer|system|unrestricted|dan)\b",
            re.IGNORECASE,
        ),
    ),
    InjectionPattern(
        "secret_exfiltration",
        re.compile(
            r"\b(jwt[_\s-]?secret|admin[_\s-]?key|mfa[_\s-]?(encryption[_\s-]?)?key|"
            r"service[_\s-]?role[_\s-]?key|api[_\s-]?key|private[_\s-]?key|"
            r"password[_\s-]?hash|environment[_\s-]?variables?|\.env\b)\b",
            re.IGNORECASE,
        ),
    ),
    InjectionPattern(
        "data_exfiltration",
        re.compile(
            r"\b(reveal|print|show|output|leak|expose|dump|list|repeat)\b"
            r"[\s\S]{0,40}?\b(secret|secrets|token|tokens|password|passwords|"
            r"credential|credentials|api[_\s-]?key)\b",
            re.IGNORECASE,
        ),
    ),
    InjectionPattern(
        "delimiter_injection",
        re.compile(
            r"(<\|(im_start|im_end|system|assistant|endoftext)\|>|"
            r"\[/?INST\]|<<\s*/?\s*SYS\s*>>|###\s*(system|assistant)\b)",
            re.IGNORECASE,
        ),
    ),
    InjectionPattern(
        "tool_override",
        re.compile(
            r"\b(call|invoke|run|execute|use)\b[\s\S]{0,40}?"
            r"\b(query_tool|read_csv_tool|read_photo_tool|validate_tool|summary_tool|export_tool)\b",
            re.IGNORECASE,
        ),
    ),
)


def detect_injection(text: str) -> Optional[str]:
    """Return the name of the first matching pattern, or ``None``."""

    candidate = (text or "").strip()
    if not candidate:
        return None
    for pattern in _PATTERNS:
        if pattern.regex.search(candidate):
            return pattern.name
    return None


def screen_agent_input(text: str) -> None:
    """Validate agent input, raising :class:`PromptInjectionError` when unsafe."""

    if len(text or "") > MAX_AGENT_INPUT_CHARS:
        raise PromptInjectionError("input_too_long")

    match = detect_injection(text)
    if match:
        raise PromptInjectionError(match)
