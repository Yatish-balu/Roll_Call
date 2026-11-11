"""Prompt-injection and untrusted-content detection (Person 2 - Phase 3).

The agent never treats user input, uploaded file contents or OCR text as
instructions. These helpers add an explicit, testable first line of defense:

* chat prompts matching known injection patterns are rejected before any AI
  tool runs;
* instructions embedded in uploaded files are logged as suspicious content but
  are still treated strictly as *data* (they are never executed).

Detection is conservative on purpose: the goal is to catch classic
"ignore previous instructions" style payloads without blocking legitimate
attendance questions.
"""

from __future__ import annotations

import base64
import binascii
import html
import re
import codecs
import unicodedata
from dataclasses import dataclass
from typing import Optional, Sequence

#: Maximum characters of user-controlled text inspected at once.
MAX_INSPECT_CHARS = 20_000

#: Maximum characters of user-controlled chat input permitted.
MAX_AGENT_INPUT_CHARS = 4000

#: Maximum characters echoed in any log/summary (never log the whole payload).
MAX_REPORT_CHARS = 200


@dataclass(frozen=True)
class InjectionFinding:
    """A prompt-injection rule that matched untrusted text."""

    rule: str
    start: int
    end: int

    def to_dict(self) -> dict:
        return {"rule": self.rule, "start": self.start, "end": self.end}


# (rule name, compiled pattern). Patterns are case-insensitive and allow
# flexible whitespace so trivial obfuscation does not bypass them.
_PATTERNS: Sequence[tuple[str, re.Pattern[str]]] = (
    (
        "ignore_instructions",
        re.compile(
            r"\b(?:ignore|ignoring|ignored|disregard|disregarding|forget|override)\s*[-_\s]+(?:(?:all|any)\s*[-_\s]+)?"
            r"(?:the\s*[-_\s]+)?(?:previous|prior|above|earlier|system)\s*[-_\s]+"
            r"(?:instructions?|prompts?|rules?|directions?|directives?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "system_prompt_exfiltration",
        re.compile(
            r"\b(?:reveal|show|print|repeat|dump|leak|output)\s+"
            r"(?:me\s+)?(?:your|the)\s+(?:system\s+prompt|hidden\s+prompt|"
            r"instructions?|developer\s+message)\b|"
            r"\b(?:system|developer|hidden|initial)\s+(?:prompt|message|instructions?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "secret_exfiltration",
        re.compile(
            r"\b(?:reveal|show|print|dump|leak|give\s+me)\s+"
            r"(?:the\s+)?(?:api\s*key|secret|password|credential|token|env(?:ironment)?\s+var|admin[_\s-]?key|jwt[_\s-]?secret|mfa[_\s-]?key)|"
            r"\b(?:jwt[_\s-]?secret|admin[_\s-]?key|mfa[_\s-]?(?:encryption[_\s-]?)?key|environment[_\s-]?variables?|\.env\b)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_escalation",
        re.compile(
            r"\b(?:act|behave|respond|pretend\s+to\s+be|you\s+are\s+now|from\s+now\s+on(?:,\s*you)?)\s+(?:as\s+)?(?:an?\s+)?"
            r"(?:admin(?:istrator)?|root|superuser|developer|system|unrestricted|dan)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "authorization_override",
        re.compile(
            r"\b(?:override|bypass|disable|skip)\s+(?:the\s+)?"
            r"(?:security|authorization|authentication|permission|access\s+control|guardrail)",
            re.IGNORECASE,
        ),
    ),
    (
        "jailbreak",
        re.compile(r"\b(?:jailbreak|developer\s+mode|do\s+anything\s+now)\b", re.IGNORECASE),
    ),
    (
        "delimiter_injection",
        re.compile(
            r"(<\|(im_start|im_end|system|assistant|endoftext)\|>|\[/?INST\]|<<\s*/?\s*SYS\s*>>|###\s*(system|assistant)\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "tool_override",
        re.compile(
            r"\b(?:call|invoke|run|execute|use)\b[\s\S]{0,40}?\b(?:query_tool|read_csv_tool|read_photo_tool|validate_tool|summary_tool|export_tool)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "instruction_boundary_spoof",
        re.compile(
            r"(?:^|\n)\s*(?:system|assistant|developer)\s*:\s*"
            r"(?:you|ignore|reveal|act|run|execute)",
            re.IGNORECASE,
        ),
    ),
    (
        "multilingual_instruction_override",
        re.compile(
            r"\b(?:ignora|ignorar|ignorez|ignoriere|olvida|olvidar|"
            r"oublie|oubliez|vergiss|negeer)\b"
            r"(?:\s+\w+){0,5}\s+"
            r"\b(?:instrucciones?|directrices?|instructions?|anweisungen|regeln)\b",
            re.IGNORECASE,
        ),
    ),
)

_HEX_CANDIDATE = re.compile(r"(?:[0-9A-Fa-f]{2}){12,}")

_HOMOGLYPHS = str.maketrans({
    "а": "a", "с": "c", "е": "e", "і": "i", "ј": "j", "к": "k",
    "м": "m", "ո": "n", "о": "o", "р": "p", "ѕ": "s", "т": "t",
    "х": "x", "у": "y", "Α": "a", "Β": "b", "Ε": "e", "Ι": "i",
    "Κ": "k", "Μ": "m", "Ν": "n", "Ο": "o", "Ρ": "p", "Τ": "t",
    "Χ": "x", "Ζ": "z",
})
_LEETSPEAK = str.maketrans({"1": "i", "0": "o", "3": "e", "4": "a", "5": "s", "7": "t"})
_COMPACT_ATTACKS = (
    re.compile(r"(?:ignore|ignoring|ignored|disregard|disregarding|forget)(?:all|the)?(?:previous|prior|above|earlier|system)(?:instructions?|prompts?|rules?|directions?|directives?)"),
    re.compile(r"(?:reveal|show|print|repeat|dump|leak|output)(?:me|your|the)?(?:systemprompt|hiddenprompt|instructions?|developermessage|apikey|secret|password|credential|token)"),
    re.compile(r"(?:bypass|disable|override|skip)(?:the)?(?:security|authorization|authentication|permission|accesscontrol|guardrail)"),
    re.compile(r"(?:act|behave|respond)as(?:an?)?(?:admin(?:istrator)?|root|superuser|developer|system)"),
)


def _strip_invisible_formatting(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    # Strip all Unicode format controls (including zero-width joiners/spaces)
    # and normalize casing before matching.
    return "".join(
        ch
        for ch in normalized
        if unicodedata.category(ch) != "Cf"
        and not (0xFE00 <= ord(ch) <= 0xFE0F)
        and not (0xE0100 <= ord(ch) <= 0xE01EF)
    )


def _normalize_untrusted(text: str) -> str:
    clean = _strip_invisible_formatting(text)
    for _ in range(2):
        clean = html.unescape(clean)
    clean = re.sub(
        r"\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})|\\x([0-9a-fA-F]{2})",
        lambda m: chr(int(next(group for group in m.groups() if group), 16)),
        clean,
    )
    return clean.translate(_HOMOGLYPHS).translate(_LEETSPEAK).lower()


def _decoded_instruction(text: str) -> Optional[tuple[str, int, int]]:
    """Inspect common Base64/hex encodings recursively, including glued tokens."""
    candidates: list[tuple[str, int, str]] = []
    for match in re.finditer(r"[A-Za-z0-9+/_=-]{16,}", text):
        token = match.group(0)
        for offset in range(min(4, len(token))):
            candidates.append((token[offset:], match.start() + offset, "base64"))
    for match in _HEX_CANDIDATE.finditer(text):
        candidates.append((match.group(0), match.start(), "hex"))

    for token, start, encoding in candidates:
        current = token
        for depth in range(3):
            try:
                if encoding == "hex":
                    if len(current) % 2:
                        break
                    raw = bytes.fromhex(current)
                else:
                    raw = base64.urlsafe_b64decode(current + "=" * (-len(current) % 4))
                decoded = raw.decode("utf-8", errors="replace")
            except (ValueError, binascii.Error):
                break
            folded = _normalize_untrusted(decoded)
            finding = _find_normalized_injection(folded)
            if finding:
                return f"{encoding}{depth + 1}_{finding.rule}", start, start + len(token)
            # Recursion only makes sense when this result remains text-like.
            printable = sum(ch.isprintable() or ch.isspace() for ch in decoded)
            if not decoded or printable / len(decoded) < 0.85:
                break
            current = decoded.strip()
            encoding = "base64"
    return None


def _find_normalized_injection(inspected: str) -> Optional[InjectionFinding]:
    for rule, pattern in _PATTERNS:
        match = pattern.search(inspected)
        if match:
            return InjectionFinding(rule=rule, start=match.start(), end=match.end())
    compact = "".join(char for char in inspected if char.isalnum())
    for index, pattern in enumerate(_COMPACT_ATTACKS):
        if pattern.search(compact):
            return InjectionFinding(rule=f"obfuscated_{index + 1}", start=0, end=len(inspected))
    return None


def find_prompt_injection(text: Optional[str]) -> Optional[InjectionFinding]:
    """Return the first injection finding in *text*, or ``None`` when clean."""
    if not text:
        return None
    # Inspect the complete bounded upload/chat value in windows. The overlap
    # catches phrases and encoded tokens that straddle a window boundary.
    stride = MAX_INSPECT_CHARS - 4096
    for offset in range(0, len(text), stride):
        cleaned = _strip_invisible_formatting(text[offset : offset + MAX_INSPECT_CHARS])
        inspected = _normalize_untrusted(cleaned)
        direct = _find_normalized_injection(inspected)
        if direct:
            return InjectionFinding(
                rule=direct.rule,
                start=offset + direct.start,
                end=offset + direct.end,
            )
        rotated = codecs.decode(inspected, "rot_13")
        rot_finding = _find_normalized_injection(rotated)
        if rot_finding:
            return InjectionFinding(
                rule="rot13_" + rot_finding.rule,
                start=offset + rot_finding.start,
                end=offset + rot_finding.end,
            )
        encoded = _decoded_instruction(cleaned)
        if encoded:
            rule, start, end = encoded
            return InjectionFinding(rule=rule, start=offset + start, end=offset + end)
    return None


def contains_prompt_injection(text: Optional[str]) -> bool:
    return find_prompt_injection(text) is not None


def safe_excerpt(text: Optional[str], limit: int = MAX_REPORT_CHARS) -> str:
    """Bounded, single-line excerpt safe for logs and error summaries."""
    if not text:
        return ""
    flat = " ".join(str(text).split())
    if len(flat) <= limit:
        return flat
    return flat[:limit] + "..."


class PromptInjectionError(ValueError):
    """Raised when agent input matches a prompt-injection pattern."""

    def __init__(self, pattern: str) -> None:
        self.pattern = pattern
        super().__init__(
            "The request was rejected because it looks like an attempt to "
            "override the assistant's instructions. Ask a normal attendance "
            "question instead."
        )


def detect_injection(text: str) -> Optional[str]:
    finding = find_prompt_injection(text)
    return finding.rule if finding else None


def screen_agent_input(text: str) -> None:
    if len(text or "") > MAX_AGENT_INPUT_CHARS:
        raise PromptInjectionError("input_too_long")
    finding = find_prompt_injection(text)
    if finding is not None:
        raise PromptInjectionError(finding.rule)

