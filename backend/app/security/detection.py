"""Suspicious activity detection foundations (IDS).

The detectors here recognise *patterns*, not single events. A single failed
login or a single denied request is normal operation and never blocks a user:
the detectors count events inside a sliding window and only emit a structured
security event once a configurable threshold is reached.

Every threshold is configurable through the environment so that a deployment
can tune sensitivity without a code change.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Optional, Tuple

from app.security.events import log_security_event

#: Window (seconds) and threshold for each detector.
DEFAULT_WINDOW_SECONDS = 300


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class DetectionThresholds:
    """Configurable detection thresholds."""

    failed_login_window_seconds: int = 900
    failed_login_threshold: int = 5
    refresh_reuse_threshold: int = 1
    access_denied_window_seconds: int = 600
    access_denied_threshold: int = 10
    student_enumeration_window_seconds: int = 300
    student_enumeration_threshold: int = 20
    file_upload_window_seconds: int = 600
    file_upload_threshold: int = 10
    file_upload_bytes_threshold: int = 50_000_000

    @classmethod
    def from_env(cls) -> "DetectionThresholds":
        return cls(
            failed_login_window_seconds=_env_int("SEC_FAILED_LOGIN_WINDOW_SECONDS", 900),
            failed_login_threshold=_env_int("SEC_FAILED_LOGIN_THRESHOLD", 5),
            refresh_reuse_threshold=_env_int("SEC_REFRESH_REUSE_THRESHOLD", 1),
            access_denied_window_seconds=_env_int("SEC_ACCESS_DENIED_WINDOW_SECONDS", 600),
            access_denied_threshold=_env_int("SEC_ACCESS_DENIED_THRESHOLD", 10),
            student_enumeration_window_seconds=_env_int(
                "SEC_STUDENT_ENUMERATION_WINDOW_SECONDS", 300
            ),
            student_enumeration_threshold=_env_int("SEC_STUDENT_ENUMERATION_THRESHOLD", 20),
            file_upload_window_seconds=_env_int("SEC_FILE_UPLOAD_WINDOW_SECONDS", 600),
            file_upload_threshold=_env_int("SEC_FILE_UPLOAD_THRESHOLD", 10),
            file_upload_bytes_threshold=_env_int("SEC_FILE_UPLOAD_BYTES_THRESHOLD", 50_000_000),
        )


class _SlidingWindow:
    """Thread-safe sliding window of (timestamp, value) observations."""

    def __init__(self, window_seconds: int) -> None:
        self.window_seconds = window_seconds
        self._events: Dict[str, Deque[Tuple[float, Any]]] = defaultdict(deque)
        self._lock = threading.Lock()

    def add(self, key: str, value: Any = 1) -> int:
        """Record an observation and return the number of observations in the window."""
        now = time.monotonic()
        with self._lock:
            bucket = self._events[key]
            bucket.append((now, value))
            cutoff = now - self.window_seconds
            while bucket and bucket[0][0] < cutoff:
                bucket.popleft()
            return len(bucket)

    def distinct(self, key: str, value: Any) -> int:
        """Record a value and return the number of *distinct* values in the window."""
        now = time.monotonic()
        with self._lock:
            bucket = self._events[key]
            bucket.append((now, value))
            cutoff = now - self.window_seconds
            while bucket and bucket[0][0] < cutoff:
                bucket.popleft()
            return len({item for _, item in bucket})

    def sum(self, key: str, value: float) -> float:
        """Record a numeric observation and return the sum inside the window."""
        now = time.monotonic()
        with self._lock:
            bucket = self._events[key]
            bucket.append((now, value))
            cutoff = now - self.window_seconds
            while bucket and bucket[0][0] < cutoff:
                bucket.popleft()
            return float(sum(item for _, item in bucket))

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


class SecurityDetector:
    """Detects suspicious activity patterns and emits security events."""

    def __init__(self, thresholds: Optional[DetectionThresholds] = None) -> None:
        self.thresholds = thresholds or DetectionThresholds.from_env()
        self._failed_logins = _SlidingWindow(self.thresholds.failed_login_window_seconds)
        self._access_denied = _SlidingWindow(self.thresholds.access_denied_window_seconds)
        self._student_lookups = _SlidingWindow(self.thresholds.student_enumeration_window_seconds)
        self._file_uploads = _SlidingWindow(self.thresholds.file_upload_window_seconds)

    # -- detectors -------------------------------------------------------
    def record_failed_login(
        self,
        *,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        reason: str = "invalid_credentials",
        request_id: Optional[str] = None,
    ) -> int:
        """Count a failed login and report a burst of failures."""
        key = f"login:{user_id or '-'}:{ip_address or '-'}"
        count = self._failed_logins.add(key)
        if count >= self.thresholds.failed_login_threshold:
            log_security_event(
                "repeated_failed_logins",
                severity="warning",
                outcome="failure",
                actor_id=user_id,
                ip_address=ip_address,
                request_id=request_id,
                details={
                    "count": count,
                    "threshold": self.thresholds.failed_login_threshold,
                    "window_seconds": self.thresholds.failed_login_window_seconds,
                    "reason": reason,
                },
            )
        return count

    def record_refresh_token_reuse(
        self,
        *,
        user_id: Optional[str] = None,
        session_family: Optional[str] = None,
        ip_address: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> int:
        """Report a refresh token that was presented twice."""
        key = f"refresh:{user_id or '-'}:{session_family or '-'}"
        count = self._access_denied.add(key)
        if count >= max(1, self.thresholds.refresh_reuse_threshold):
            log_security_event(
                "refresh_token_reuse",
                severity="critical",
                outcome="failure",
                actor_id=user_id,
                ip_address=ip_address,
                request_id=request_id,
                details={
                    "count": count,
                    "session_family": session_family,
                    "threshold": self.thresholds.refresh_reuse_threshold,
                },
            )
        return count

    def record_access_denied(
        self,
        *,
        actor_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        path: Optional[str] = None,
        status_code: int = 403,
        request_id: Optional[str] = None,
    ) -> int:
        """Count denied accesses and report a burst."""
        key = f"denied:{actor_id or '-'}:{ip_address or '-'}"
        count = self._access_denied.add(key)
        if count >= self.thresholds.access_denied_threshold:
            log_security_event(
                "repeated_access_denied",
                severity="warning",
                outcome="failure",
                actor_id=actor_id,
                ip_address=ip_address,
                request_id=request_id,
                details={
                    "count": count,
                    "threshold": self.thresholds.access_denied_threshold,
                    "window_seconds": self.thresholds.access_denied_window_seconds,
                    "status_code": status_code,
                    "path": path,
                },
            )
        return count

    def record_student_lookup(
        self,
        *,
        actor_id: Optional[str] = None,
        usn: Optional[str] = None,
        ip_address: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> int:
        """Count distinct student identifiers looked up by one caller."""
        if not usn:
            return 0
        key = f"students:{actor_id or '-'}:{ip_address or '-'}"
        distinct = self._student_lookups.distinct(key, str(usn).upper())
        if distinct >= self.thresholds.student_enumeration_threshold:
            log_security_event(
                "student_data_enumeration",
                severity="warning",
                outcome="suspicious",
                actor_id=actor_id,
                ip_address=ip_address,
                request_id=request_id,
                details={
                    "distinct_students": distinct,
                    "threshold": self.thresholds.student_enumeration_threshold,
                    "window_seconds": self.thresholds.student_enumeration_window_seconds,
                },
            )
        return distinct

    def record_file_upload(
        self,
        *,
        actor_id: Optional[str] = None,
        size_bytes: int = 0,
        ip_address: Optional[str] = None,
        request_id: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> int:
        """Count uploads and report abnormal upload activity."""
        key = f"uploads:{actor_id or '-'}:{ip_address or '-'}"
        count = self._file_uploads.add(key)
        total_bytes = self._file_uploads.sum(f"bytes:{actor_id or '-'}:{ip_address or '-'}", size_bytes)
        if count >= self.thresholds.file_upload_threshold or total_bytes >= self.thresholds.file_upload_bytes_threshold:
            log_security_event(
                "abnormal_file_upload_activity",
                severity="warning",
                outcome="suspicious",
                actor_id=actor_id,
                ip_address=ip_address,
                request_id=request_id,
                details={
                    "uploads": count,
                    "upload_threshold": self.thresholds.file_upload_threshold,
                    "total_bytes": int(total_bytes),
                    "byte_threshold": self.thresholds.file_upload_bytes_threshold,
                    "filename": filename,
                },
            )
        return count

    def record_audit_verification_failure(
        self,
        *,
        details: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> None:
        """Report a failed audit chain verification."""
        log_security_event(
            "audit_chain_verification_failed",
            severity="critical",
            outcome="failure",
            request_id=request_id,
            details=details or {},
        )

    def record_decoy_probe(
        self,
        *,
        decoy_kind: str,
        actor_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        request_id: Optional[str] = None,
        path: Optional[str] = None,
    ) -> None:
        """Report access to a honeypot record."""
        log_security_event(
            "decoy_accessed",
            severity="warning",
            outcome="suspicious",
            actor_id=actor_id,
            ip_address=ip_address,
            request_id=request_id,
            details={"decoy_kind": decoy_kind, "path": path},
        )

    def reset(self) -> None:
        """Clear all windows (used by tests and by the rate limiter reset)."""
        self._failed_logins.reset()
        self._access_denied.reset()
        self._student_lookups.reset()
        self._file_uploads.reset()


#: Process-wide detector instance used by the API layer.
detector = SecurityDetector()
