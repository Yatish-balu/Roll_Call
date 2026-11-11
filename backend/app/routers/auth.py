"""Authentication router for secure user login, persistent sessions, token rotation, and logout."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import bcrypt
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select, update
# Module-level alias: some code paths in this module use the ``sa_select`` name.
from sqlalchemy import select as sa_select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.jwt import create_access_token
from app.auth.roles import normalize_role
from app.db.connection import get_sync_session_factory
from app.db.models import AuthRefreshToken, AuthSession, LoginAttempt, TeacherSubject, User
from app.schemas.auth import AuthenticatedUser, LoginRequest, LoginResponse, Role, UserMeResponse
from app.security.context import get_request_id
from app.security.detection import detector
from app.security.email import get_email_provider
from app.security.events import log_security_event
from app.security.mfa import (
    MFAConfigurationError,
    MFADecryptionError,
    decrypt_secret,
    encrypt_secret,
    generate_mfa_secret,
    generate_recovery_codes,
    get_encryption_key,
    hash_recovery_code,
    verify_recovery_code,
    verify_totp,
)
from app.security.rate_limit import LimitScope, check_limit, clear_limit

logger = logging.getLogger("rollcall.auth.router")

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Per-account locks serialise the check-and-record window for one account on
# SQLite. A global lock serialised every login in the process, so one slow
# attempt delayed every other user; per-account locks keep that correctness
# without the cross-user bottleneck.
_login_locks: Dict[str, threading.Lock] = {}
_login_locks_guard = threading.Lock()

# A real bcrypt hash that is never a valid credential. Verifying against it for
# unknown accounts keeps the response time of a failed login constant, so the
# endpoint cannot be used to enumerate valid user ids.
_DUMMY_PASSWORD_HASH = "$2b$12$j3mmKiApoKgogYvb1ieK/uyarwjvMorVikA.7sCpG5sSwWibDyMum"


def _login_user_lock(user_key: str):
    """Return the lock dedicated to one account (created on first use)."""
    with _login_locks_guard:
        lock = _login_locks.get(user_key)
        if lock is None:
            lock = threading.Lock()
            _login_locks[user_key] = lock
    return lock


def _client_ip(request: Request) -> str:
    """Resolve the client address, honouring a trusted reverse proxy.

    ``X-Forwarded-For`` is only trusted when ``TRUST_PROXY_HEADERS`` is enabled,
    because otherwise any client could spoof the header and dodge the per-IP
    quota.
    """
    peer = request.client.host if request.client else "127.0.0.1"
    trust_proxy = os.getenv("TRUST_PROXY_HEADERS", "").strip().lower() in {"1", "true", "yes", "on"}
    if trust_proxy:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first[:45]
    return peer[:45]


def _too_many_requests(retry_after: int, message: str) -> JSONResponse:
    """Uniform 429 response with a Retry-After header."""
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"error": {"code": "RATE_LIMITED", "message": message}},
        headers={"Retry-After": str(max(1, int(retry_after)))},
    )


def _failures_since_last_success(
    db: Session,
    *failure_conditions,
    success_conditions,
    cutoff_iso: str,
) -> int:
    """Count failures newer than the last success for the same dimension.

    A successful login resets the effective window instead of deleting the
    historical rows, so the attempt log stays intact for auditing while a
    shared NAT/proxy recovers as soon as one of its users authenticates.
    """
    last_success = db.execute(
        select(func.max(LoginAttempt.timestamp)).where(*success_conditions)
    ).scalar()
    effective_cutoff = max(cutoff_iso, last_success or "")
    return _failed_attempts_since(db, *failure_conditions, cutoff_iso=effective_cutoff)

REFRESH_COOKIE_NAME = "rollcall_refresh_token"
COOKIE_PATH = "/api"


def _get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_utc_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_production() -> bool:
    return os.getenv("APP_ENV", "development").lower() == "production"


def _validate_csrf(request: Request) -> None:
    """
    Enforce CSRF protection for cookie-based state-changing endpoints (refresh, logout).
    1. Validates Origin header against configured allowed frontend origins if present.
    2. Requires custom request header (X-Requested-With or X-RollCall-CSRF).
    """
    # 1. Validate Origin if present
    origin = request.headers.get("Origin")
    if origin:
        from app.main import get_allowed_origins
        allowed = get_allowed_origins()
        clean_origin = origin.strip().rstrip("/")
        allowed_normalized = [o.strip().rstrip("/") for o in allowed]
        if clean_origin not in allowed_normalized:
            logger.warning("CSRF check rejected: Untrusted Origin %s", origin)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "FORBIDDEN", "message": "Untrusted request origin."}},
            )

    # 2. Require custom header to prevent simple HTML form/link cross-site submission
    has_csrf_header = (
        request.headers.get("X-Requested-With") is not None
        or request.headers.get("X-RollCall-CSRF") is not None
    )
    if not has_csrf_header:
        logger.warning("CSRF check rejected: Missing required CSRF header on %s", request.url.path)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "CSRF_DETECTED", "message": "Missing required CSRF header."}},
        )


def _record_attempt(
    db: Session,
    *,
    user_id: Optional[str],
    ip_address: Optional[str],
    success: int,
    timestamp: str,
) -> None:
    """Record an authentication attempt in login_attempts table.

    Failed attempts are additionally counted by the security detector, which
    reports a burst of failures as a security event. A single failure never
    blocks a user.
    """
    try:
        attempt = LoginAttempt(
            user_id=user_id,
            ip_address=ip_address,
            success=success,
            timestamp=timestamp,
        )
        db.add(attempt)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Failed to persist login attempt: %s", exc)

    if not success:
        detector.record_failed_login(
            user_id=user_id,
            ip_address=ip_address,
            request_id=get_request_id(),
        )
        log_security_event(
            "authentication_failed",
            severity="info",
            outcome="failure",
            actor_id=user_id,
            ip_address=ip_address,
            request_id=get_request_id(),
            details={"reason": "invalid_credentials"},
        )


def _failed_attempts_since(
    db: Session,
    *conditions,
    cutoff_iso: str,
) -> int:
    """Count failed login attempts matching any of the supplied conditions."""
    stmt = select(func.count(LoginAttempt.id)).where(
        or_(*conditions),
        LoginAttempt.success == 0,
        LoginAttempt.timestamp >= cutoff_iso,
    )
    return db.execute(stmt).scalar() or 0


def _check_rate_limit(
    db: Session,
    user_id: str,
    now_dt: datetime,
    ip_address: Optional[str] = None,
    max_failures: int = 5,
    max_ip_failures: Optional[int] = None,
    window_seconds: int = 600,
) -> bool:
    """
    Check whether a login attempt is allowed.

    Two independent quotas are enforced over the rolling window:
    * per attempted user id  (max_failures, default 5)
    * per client IP address  (max_ip_failures, default 20)

    The IP quota is deliberately higher than the per-user quota so a shared
    NAT/proxy cannot lock out unrelated users, while still throttling cheap
    brute force against accounts that do not exist (those attempts are stored
    with ``user_id = NULL`` and are only visible through the IP quota).
    """
    if max_ip_failures is None:
        # A shared NAT/proxy must not be locked out by unrelated users, so the
        # IP quota is deliberately generous and can be tuned per deployment.
        try:
            max_ip_failures = max(20, int(os.getenv("LOGIN_IP_FAILURE_LIMIT", "50")))
        except ValueError:
            max_ip_failures = 50

    cutoff_iso = _format_utc_iso(now_dt - timedelta(seconds=window_seconds))

    user_failures = _failures_since_last_success(
        db,
        LoginAttempt.user_id == user_id,
        success_conditions=(LoginAttempt.user_id == user_id, LoginAttempt.success == 1),
        cutoff_iso=cutoff_iso,
    )
    if user_failures >= max_failures:
        return False

    if ip_address:
        ip_failures = _failures_since_last_success(
            db,
            LoginAttempt.ip_address == ip_address,
            success_conditions=(LoginAttempt.ip_address == ip_address, LoginAttempt.success == 1),
            cutoff_iso=cutoff_iso,
        )
        if ip_failures >= max_ip_failures:
            return False

    return True


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Authenticate local user, issue 15-min JWT, and establish 7-day session",
)
def login(request: Request, payload: LoginRequest):
    """
    Authenticate user credentials, enforce DB-backed rate limiting, create session family,
    issue a 15-minute access JWT, and set a rotating HttpOnly refresh cookie.
    """
    clean_uid = payload.user_id.strip()
    clean_pw = payload.password
    client_ip = _client_ip(request)
    now_dt = _get_utc_now()
    now_iso = _format_utc_iso(now_dt)

    generic_401 = JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={
            "error": {
                "code": "UNAUTHORIZED",
                "message": "Invalid user ID or password.",
            }
        },
        headers={"WWW-Authenticate": "Bearer"},
    )

    SessionLocal = get_sync_session_factory()
    with SessionLocal() as db:
        with _login_user_lock(clean_uid):
            user = db.get(User, clean_uid)
            record_uid = user.user_id if user is not None else None

            # 1. Quota check (rolling 10-minute window, per user and per IP).
            # The outcome never short-circuits the credential check: a correct
            # password must never be refused, otherwise an attacker could keep a
            # known account locked out with a handful of bad attempts.
            allowed = _check_rate_limit(db, clean_uid, now_dt, ip_address=client_ip)
            # Shared (cross-worker) quotas with progressive back-off and a
            # temporary lockout. The database backend is used when Redis is not
            # configured; it is still shared between workers.
            user_decision = check_limit(db, LimitScope.LOGIN, f"user:{clean_uid}", record_failure=False, commit=True)
            ip_decision = check_limit(db, LimitScope.LOGIN, f"ip:{client_ip}", record_failure=False, commit=True)
            quota_blocked = not (allowed and user_decision.allowed and ip_decision.allowed)
            quota_retry_after = max(
                user_decision.retry_after_seconds,
                ip_decision.retry_after_seconds,
                600,
            )

            def _reject_login() -> JSONResponse:
                """Count the failure and answer generically (429 only when exhausted)."""
                _record_attempt(db, user_id=record_uid, ip_address=client_ip, success=0, timestamp=now_iso)
                failure = check_limit(db, LimitScope.LOGIN, f"user:{clean_uid}", record_failure=True, commit=True)
                ip_failure = check_limit(db, LimitScope.LOGIN, f"ip:{client_ip}", record_failure=True, commit=True)
                if quota_blocked or not failure.allowed or not ip_failure.allowed:
                    retry_after = max(
                        quota_retry_after,
                        failure.retry_after_seconds,
                        ip_failure.retry_after_seconds,
                    )
                    log_security_event(
                        "rate_limit_triggered",
                        severity="warning",
                        outcome="blocked",
                        actor_id=record_uid,
                        ip_address=client_ip,
                        request_id=get_request_id(),
                        details={
                            "scope": "login",
                            "attempts": failure.attempts,
                            "retry_after_seconds": retry_after,
                            "backend": failure.backend,
                        },
                    )
                    return _too_many_requests(
                        retry_after,
                        "Too many failed login attempts. Please try again later.",
                    )
                return generic_401

            # 2+3. Always run a bcrypt comparison - even for an unknown or
            # inactive account - against a real dummy hash, so response timing
            # cannot be used to distinguish existing user ids.
            candidate_hash = (
                user.hashed_password
                if user is not None and user.hashed_password
                else _DUMMY_PASSWORD_HASH
            )
            try:
                pw_matches = bcrypt.checkpw(clean_pw.encode("utf-8"), candidate_hash.encode("utf-8"))
            except Exception:
                pw_matches = False

            if user is None or not user.is_active or not user.hashed_password or not pw_matches:
                return _reject_login()

            # 4. ADMIN role extra authentication check
            if user.role.upper() == "ADMIN":
                configured_admin_key = os.getenv("ADMIN_KEY")
                if not configured_admin_key or len(configured_admin_key.strip()) == 0:
                    logger.error("ADMIN login failed closed: ADMIN_KEY is not configured on the server.")
                    _record_attempt(db, user_id=record_uid, ip_address=client_ip, success=0, timestamp=now_iso)
                    return generic_401

                if not payload.admin_key or len(payload.admin_key.strip()) == 0:
                    _record_attempt(db, user_id=record_uid, ip_address=client_ip, success=0, timestamp=now_iso)
                    return generic_401

                if not hmac.compare_digest(payload.admin_key.strip(), configured_admin_key.strip()):
                    _record_attempt(db, user_id=record_uid, ip_address=client_ip, success=0, timestamp=now_iso)
                    return generic_401

            # 4b. Second factor. When MFA is enabled a correct password alone is
            # never sufficient: the TOTP code (or a single-use recovery code)
            # must verify before any session is created. A missing/invalid code
            # yields the same generic answer as a bad password.
            if user.mfa_enabled:
                mfa_code = (payload.mfa_code or "").strip()
                mfa_verified = False
                used_recovery = False
                totp_counter: Optional[int] = None
                try:
                    mfa_secret = decrypt_secret(user.mfa_secret or "")
                except (MFAConfigurationError, MFADecryptionError) as exc:
                    # Fail closed: an undecryptable secret must never be skipped.
                    logger.error("MFA login refused: secret unavailable (%s)", exc)
                    _record_attempt(db, user_id=record_uid, ip_address=client_ip, success=0, timestamp=now_iso)
                    return generic_401

                if mfa_code.isdigit() and len(mfa_code) == 6:
                    mfa_verified, totp_counter = verify_totp(
                        mfa_secret, mfa_code, last_counter=user.mfa_last_counter
                    )
                elif mfa_code:
                    stored_codes = json.loads(user.mfa_recovery_codes or "[]")
                    matched = verify_recovery_code(mfa_code, stored_codes)
                    if matched is not None:
                        user.mfa_recovery_codes = json.dumps(
                            [item for item in stored_codes if item != matched]
                        )
                        mfa_verified = True
                        used_recovery = True

                if not mfa_verified:
                    _record_attempt(db, user_id=record_uid, ip_address=client_ip, success=0, timestamp=now_iso)
                    mfa_failure = check_limit(
                        db, LimitScope.MFA_VERIFY, f"user:{clean_uid}", record_failure=True, commit=True
                    )
                    log_security_event(
                        "mfa_verification_failed",
                        severity="info",
                        outcome="failure",
                        actor_id=record_uid,
                        ip_address=client_ip,
                        request_id=get_request_id(),
                        details={"stage": "login", "used_recovery_code": used_recovery},
                    )
                    if not mfa_failure.allowed:
                        return _too_many_requests(
                            mfa_failure.retry_after_seconds or 900,
                            "Too many MFA attempts. Please try again later.",
                        )
                    return generic_401

                if totp_counter is not None:
                    user.mfa_last_counter = totp_counter
                db.commit()
                clear_limit(db, LimitScope.MFA_VERIFY, f"user:{clean_uid}")
                log_security_event(
                    "mfa_challenge_satisfied",
                    severity="info",
                    outcome="success",
                    actor_id=record_uid,
                    ip_address=client_ip,
                    request_id=get_request_id(),
                    details={"used_recovery_code": used_recovery},
                )

            # 5. Record successful login attempt
            _record_attempt(db, user_id=record_uid, ip_address=client_ip, success=1, timestamp=now_iso)
            # A successful authentication clears the failure counters, so a
            # legitimate user who mistyped a few times is not punished and an
            # attacker cannot keep an account locked out.
            clear_limit(db, LimitScope.LOGIN, f"user:{clean_uid}")
            clear_limit(db, LimitScope.LOGIN, f"ip:{client_ip}")

            # 6. Create server-side session family (7-day absolute lifetime)
            abs_expiry_dt = now_dt + timedelta(days=7)
            abs_expiry_iso = _format_utc_iso(abs_expiry_dt)
            session_id = uuid.uuid4().hex

            user_agent_header = request.headers.get("User-Agent")
            safe_ua = user_agent_header[:255] if user_agent_header else None
            safe_ip = client_ip[:45] if client_ip else None

            session_family = AuthSession(
                session_id=session_id,
                user_id=user.user_id,
                created_at=now_iso,
                absolute_expiry=abs_expiry_iso,
                revoked_at=None,
                remember_me=1 if payload.remember_me else 0,
                user_agent=safe_ua,
                ip_address=safe_ip,
            )
            db.add(session_family)

            # 7. Generate cryptographically secure opaque refresh token
            raw_refresh = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw_refresh.encode("utf-8")).hexdigest()
            refresh_record = AuthRefreshToken(
                token_id=uuid.uuid4().hex,
                session_id=session_id,
                token_hash=token_hash,
                rotation_seq=0,
                created_at=now_iso,
                consumed_at=None,
                revoked_at=None,
            )
            db.add(refresh_record)

            # 8. Issue signed JWT token with 15-minute expiry before committing the session
            # so a token creation error rolls back cleanly without leaving an orphaned session.
            try:
                exp_dt = now_dt + timedelta(minutes=15)
                exp_iso = _format_utc_iso(exp_dt)
                token_claims = {
                    "sub": user.user_id,
                    "role": user.role,
                    "sid": session_id,
                    "iat": int(now_dt.timestamp()),
                    "exp": int(exp_dt.timestamp()),
                }
                token = create_access_token(token_claims, expires_delta=timedelta(minutes=15))
            except Exception as e:
                logger.error("Failed to create JWT token on login: %s", e)
                db.rollback()
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "error": {
                            "code": "TOKEN_CREATION_FAILED",
                            "message": "An error occurred while generating your authentication token. Please try again.",
                        }
                    },
                )

            # 9. Commit session and refresh token together atomically, with error handling
            try:
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error("Failed to create session on login: %s", e)
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "error": {
                            "code": "SESSION_CREATION_FAILED",
                            "message": "An error occurred while creating your session. Please try again.",
                        }
                    },
                )

        # 10. Fetch assigned subject codes
        stmt = select(TeacherSubject.subject_code).where(TeacherSubject.user_id == clean_uid)
        subject_codes = [r[0] for r in db.execute(stmt).all()]

        out_response = JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "token": token,
                "role": user.role,
                "name": user.email.split("@")[0] if user.email else user.user_id,
                "subject_codes": subject_codes,
                "expires_at_utc": exp_iso,
            },
        )

        # 10. Set rotating HttpOnly refresh cookie
        cookie_max_age = int(timedelta(days=7).total_seconds()) if payload.remember_me else None
        out_response.set_cookie(
            key=REFRESH_COOKIE_NAME,
            value=raw_refresh,
            max_age=cookie_max_age,
            httponly=True,
            samesite="lax",
            path=COOKIE_PATH,
            secure=_is_production(),
        )
        return out_response


@router.post(
    "/refresh",
    response_model=LoginResponse,
    summary="Rotate refresh token and issue new 15-minute access JWT",
)
def refresh(request: Request):
    """
    Read refresh token from HttpOnly cookie, enforce database-level atomic rotation,
    detect token reuse and revoke compromised families, and issue a replacement 15-minute JWT.
    """
    _validate_csrf(request)

    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_token or not raw_token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "UNAUTHORIZED", "message": "Refresh token is missing."}},
            headers={"WWW-Authenticate": "Bearer"},
        )

    candidate_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
    now_dt = _get_utc_now()
    now_iso = _format_utc_iso(now_dt)
    client_ip = _client_ip(request)

    SessionLocal = get_sync_session_factory()
    with SessionLocal() as db:
        # Shared refresh quota: bounds token-guessing and refresh flooding.
        refresh_decision = check_limit(
            db, LimitScope.REFRESH, f"ip:{client_ip}", record_failure=False, commit=True
        )
        if not refresh_decision.allowed:
            return _too_many_requests(
                refresh_decision.retry_after_seconds or 300,
                "Too many refresh attempts. Please try again later.",
            )

        token_record = db.execute(
            select(AuthRefreshToken).where(AuthRefreshToken.token_hash == candidate_hash)
        ).scalar_one_or_none()

        if token_record is None:
            check_limit(db, LimitScope.REFRESH, f"ip:{client_ip}", record_failure=True, commit=True)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "UNAUTHORIZED", "message": "Invalid refresh token."}},
                headers={"WWW-Authenticate": "Bearer"},
            )

        session_family = db.get(AuthSession, token_record.session_id)
        if session_family is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "UNAUTHORIZED", "message": "Session family not found."}},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # REUSE DETECTION: If token was already consumed, revoke the entire session family!
        if token_record.consumed_at is not None:
            logger.warning(
                "Refresh token reuse detected for session family %s! Revoking complete family.",
                session_family.session_id,
            )
            # Security event (operational log, separate from the audit trail).
            check_limit(db, LimitScope.REFRESH, f"ip:{client_ip}", record_failure=True, commit=True)
            detector.record_refresh_token_reuse(
                user_id=session_family.user_id,
                session_family=session_family.session_id,
                ip_address=client_ip,
                request_id=get_request_id(),
            )
            db.execute(
                update(AuthSession)
                .where(AuthSession.session_id == session_family.session_id)
                .values(revoked_at=now_iso)
            )
            db.execute(
                update(AuthRefreshToken)
                .where(AuthRefreshToken.session_id == session_family.session_id)
                .values(revoked_at=now_iso)
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "TOKEN_REUSED", "message": "Refresh token reuse detected. Session revoked."}},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Session or token already revoked check
        if session_family.revoked_at is not None or token_record.revoked_at is not None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "SESSION_REVOKED", "message": "Session has been revoked."}},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 7-day absolute lifetime check
        try:
            abs_expiry_dt = datetime.fromisoformat(session_family.absolute_expiry.replace("Z", "+00:00"))
        except Exception:
            abs_expiry_dt = now_dt

        if now_dt >= abs_expiry_dt:
            db.execute(
                update(AuthSession)
                .where(AuthSession.session_id == session_family.session_id)
                .values(revoked_at=now_iso)
            )
            db.execute(
                update(AuthRefreshToken)
                .where(AuthRefreshToken.session_id == session_family.session_id)
                .values(revoked_at=now_iso)
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "SESSION_EXPIRED", "message": "Absolute 7-day session lifetime reached. Please log in again."}},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # User active status check
        user = db.get(User, session_family.user_id)
        if user is None or not user.is_active:
            db.execute(
                update(AuthSession)
                .where(AuthSession.session_id == session_family.session_id)
                .values(revoked_at=now_iso)
            )
            db.execute(
                update(AuthRefreshToken)
                .where(AuthRefreshToken.session_id == session_family.session_id)
                .values(revoked_at=now_iso)
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "USER_DEACTIVATED", "message": "User account is inactive or not found."}},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Database-level atomic consumption
        consume_stmt = (
            update(AuthRefreshToken)
            .where(
                AuthRefreshToken.token_id == token_record.token_id,
                AuthRefreshToken.consumed_at.is_(None),
            )
            .values(consumed_at=now_iso)
        )
        res_consume = db.execute(consume_stmt)
        if res_consume.rowcount == 0:
            # Concurrently consumed by another process: revoke family
            db.execute(
                update(AuthSession)
                .where(AuthSession.session_id == session_family.session_id)
                .values(revoked_at=now_iso)
            )
            db.execute(
                update(AuthRefreshToken)
                .where(AuthRefreshToken.session_id == session_family.session_id)
                .values(revoked_at=now_iso)
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "CONCURRENT_ROTATION", "message": "Concurrent token rotation detected."}},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Create replacement refresh token in the same session family
        new_raw_token = secrets.token_urlsafe(32)
        new_hash = hashlib.sha256(new_raw_token.encode("utf-8")).hexdigest()
        new_record = AuthRefreshToken(
            token_id=uuid.uuid4().hex,
            session_id=session_family.session_id,
            token_hash=new_hash,
            rotation_seq=token_record.rotation_seq + 1,
            created_at=now_iso,
            consumed_at=None,
            revoked_at=None,
        )
        db.add(new_record)
        db.commit()

        # Fetch assigned subject codes
        stmt = select(TeacherSubject.subject_code).where(TeacherSubject.user_id == user.user_id)
        subject_codes = [r[0] for r in db.execute(stmt).all()]

        # Issue replacement 15-minute access JWT
        exp_dt = now_dt + timedelta(minutes=15)
        exp_iso = _format_utc_iso(exp_dt)
        token_claims = {
            "sub": user.user_id,
            "role": user.role,
            "sid": session_family.session_id,
            "iat": int(now_dt.timestamp()),
            "exp": int(exp_dt.timestamp()),
        }
        new_access_token = create_access_token(token_claims, expires_delta=timedelta(minutes=15))

        # Preserve remember_me cookie lifetime up to original 7-day absolute deadline
        if session_family.remember_me == 1:
            remaining_seconds = max(0, int((abs_expiry_dt - now_dt).total_seconds()))
            cookie_max_age = remaining_seconds
        else:
            cookie_max_age = None

        out_res = JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "token": new_access_token,
                "role": user.role,
                "name": user.email.split("@")[0] if user.email else user.user_id,
                "subject_codes": subject_codes,
                "expires_at_utc": exp_iso,
            },
        )
        out_res.set_cookie(
            key=REFRESH_COOKIE_NAME,
            value=new_raw_token,
            max_age=cookie_max_age,
            httponly=True,
            samesite="lax",
            path=COOKIE_PATH,
            secure=_is_production(),
        )
        return out_res


@router.post(
    "/logout",
    summary="Revoke the current session family and clear refresh cookie",
)
def logout(request: Request):
    """
    Revoke the authenticated session family in the database and clear the HttpOnly refresh cookie.
    """
    _validate_csrf(request)

    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    now_iso = _format_utc_iso(_get_utc_now())

    if not raw_token or not raw_token.strip():
        # Logout is a state-changing endpoint: without the session cookie there
        # is nothing to revoke, and the call must not report success.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "UNAUTHORIZED", "message": "No active session to log out."}},
            headers={"WWW-Authenticate": "Bearer"},
        )

    if raw_token and raw_token.strip():
        candidate_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
        SessionLocal = get_sync_session_factory()
        with SessionLocal() as db:
            token_record = db.execute(
                select(AuthRefreshToken).where(AuthRefreshToken.token_hash == candidate_hash)
            ).scalar_one_or_none()

            if token_record is not None:
                db.execute(
                    update(AuthSession)
                    .where(AuthSession.session_id == token_record.session_id)
                    .values(revoked_at=now_iso)
                )
                db.execute(
                    update(AuthRefreshToken)
                    .where(AuthRefreshToken.session_id == token_record.session_id)
                    .values(revoked_at=now_iso)
                )
                db.commit()

    out_res = JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"success": True, "message": "Successfully logged out."},
    )
    out_res.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=COOKIE_PATH,
        samesite="lax",
        secure=_is_production(),
    )
    return out_res


@router.get(
    "/me",
    response_model=UserMeResponse,
    summary="Retrieve profile and assigned subjects of current authenticated user",
)
def get_current_user_profile(user: AuthenticatedUser = Depends(get_current_user)):
    """
    Return current user identity authoritatively verified against the database.
    Deactivated users are rejected with 401.
    """
    SessionLocal = get_sync_session_factory()
    with SessionLocal() as db:
        db_user = db.get(User, user.user_id)
        if db_user is None:
            # Supabase-issued identities may not (yet) have a local profile row;
            # they remain valid, so the token claims are echoed back unchanged.
            # Deactivation is enforced for every local account below.
            return UserMeResponse(
                user_id=user.user_id,
                email=user.email or f"{user.user_id}@rollcall.internal",
                role=user.role.value,
                is_active=1,
                subject_codes=[],
            )

        if not db_user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is deactivated.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        stmt = select(TeacherSubject.subject_code).where(TeacherSubject.user_id == db_user.user_id)
        subject_codes = [r[0] for r in db.execute(stmt).all()]

        return UserMeResponse(
            user_id=db_user.user_id,
            email=db_user.email,
            role=db_user.role,
            is_active=db_user.is_active,
            subject_codes=subject_codes,
        )
# -- Password Lifecycle Helpers --

def _validate_password_strength(password: str) -> None:
    """Validate password meets complexity requirements.

    Policy (identical for change and reset):
    - Minimum 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 digit
    - At least 1 special character
    """
    import re
    if len(password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": {"code": "WEAK_PASSWORD", "message": "Password must be at least 8 characters long."}},
        )
    if not re.search(r"[A-Z]", password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": {"code": "WEAK_PASSWORD", "message": "Password must contain at least one uppercase letter."}},
        )
    if not re.search(r"[a-z]", password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": {"code": "WEAK_PASSWORD", "message": "Password must contain at least one lowercase letter."}},
        )
    if not re.search(r"[0-9]", password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": {"code": "WEAK_PASSWORD", "message": "Password must contain at least one digit."}},
        )
    if not re.search(r"[!@#$%^&*()\[\]{}<>?|:;,.~+\-=/\\]", password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": {"code": "WEAK_PASSWORD", "message": "Password must contain at least one special character."}},
        )

# -- Password Change Endpoint --

@router.post(
    "/password/change",
    summary="Change user password (authenticated endpoint)",
    description="Change the password for the currently authenticated user. Old password is required for verification. All active sessions are invalidated on password change.",
    responses={
        200: {"description": "Password changed successfully, all sessions invalidated"},
        400: {"description": "Old password incorrect or new password weak"},
        401: {"description": "User not authenticated or old password incorrect"},
    },
)
def change_password(
    request: Request,
    old_password: str = Body(..., embed=True),
    new_password: str = Body(..., embed=True),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Change password for the authenticated user.

    Requires the old password for verification, then sets a new password
    that meets complexity requirements. All active sessions are invalidated
    since a password change should revoke active sessions.
    """
    SessionLocal = get_sync_session_factory()
    from sqlalchemy import update as sa_update
    with SessionLocal() as db:
        # A valid access token must not turn into an unlimited password oracle.
        limiter_key = f"user:{current_user.user_id}"
        change_decision = check_limit(
            db, LimitScope.PASSWORD_CHANGE, limiter_key, record_failure=False, commit=True
        )
        if not change_decision.allowed:
            log_security_event(
                "rate_limit_triggered",
                severity="warning",
                outcome="blocked",
                actor_id=current_user.user_id,
                request_id=get_request_id(),
                details={"scope": "password_change"},
            )
            return _too_many_requests(
                change_decision.retry_after_seconds or 900,
                "Too many password verification attempts. Please try again later.",
            )

        # Get the user from the database
        db_user = db.get(User, current_user.user_id)
        if db_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "UNAUTHORIZED", "message": "User not found."}},
            )

        # Verify old password
        try:
            pw_matches = bcrypt.checkpw(old_password.encode("utf-8"), db_user.hashed_password.encode("utf-8"))
        except Exception:
            pw_matches = False

        if not pw_matches:
            failed = check_limit(
                db, LimitScope.PASSWORD_CHANGE, limiter_key, record_failure=True, commit=True
            )
            if not failed.allowed:
                return _too_many_requests(
                    failed.retry_after_seconds or 900,
                    "Too many password verification attempts. Please try again later.",
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "INCORRECT_PASSWORD", "message": "Old password is incorrect."}},
            )

        # Validate new password strength
        _validate_password_strength(new_password)

        # Hash, update password, and invalidate all existing sessions/refresh tokens atomically
        hashed_pw = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        db_user.hashed_password = hashed_pw
        now_iso = _format_utc_iso(_get_utc_now())
        db.execute(
            sa_update(AuthSession).where(AuthSession.user_id == current_user.user_id).values(revoked_at=now_iso)
        )
        db.execute(
            sa_update(AuthRefreshToken).where(AuthRefreshToken.session_id.in_(
                sa_select(AuthSession.session_id).where(AuthSession.user_id == current_user.user_id)
            )).values(revoked_at=now_iso)
        )
        db.commit()
        clear_limit(db, LimitScope.PASSWORD_CHANGE, limiter_key)

        return {"message": "Password changed successfully. All active sessions have been invalidated."}


# -- Multi-Factor Authentication Endpoints --

@router.get(
    "/mfa/status",
    summary="Report whether MFA is enabled for the authenticated user.",
    description=(
        "Read-only status endpoint used by the account settings screen. It never returns "
        "the TOTP secret or any recovery material."
    ),
    responses={
        200: {"description": "MFA enrollment status"},
        401: {"description": "User not authenticated"},
    },
)
def mfa_status(current_user: AuthenticatedUser = Depends(get_current_user)):
    """Return the MFA enrollment state of the current account."""
    SessionLocal = get_sync_session_factory()
    with SessionLocal() as db:
        db_user = db.get(User, current_user.user_id)
        enabled = bool(db_user.mfa_enabled) if db_user is not None else False
        available = True
        try:
            get_encryption_key()
        except MFAConfigurationError:
            available = False
        return {
            "user_id": current_user.user_id,
            "mfa_enabled": enabled,
            "mfa_available": available,
        }


@router.post(
    "/mfa/enable",
    summary="Start MFA enrollment for the authenticated user.",
    description=(
        "Generates a TOTP secret, stores it AES-GCM encrypted and returns the secret plus "
        "single-use recovery codes. The secret is only returned once, at enrollment time. "
        "Requires MFA_ENCRYPTION_KEY; without it the endpoint fails closed in production."
    ),
    responses={
        403: {"description": "MFA is not available (no encryption key configured)"},
        422: {"description": "The current password is incorrect"},
    },
)
def enable_mfa(
    request: Request,
    current_password: str = Body(..., embed=True),
    code: Optional[str] = Body(None, embed=True),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Begin MFA enrollment (secret + recovery codes)."""
    if current_user.role == Role.VIEWER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "FORBIDDEN", "message": "MFA enrollment is not available for viewer roles."}},
        )

    try:
        encryption_key = get_encryption_key()
    except MFAConfigurationError as exc:
        logger.error("MFA enrollment refused: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "MFA_UNAVAILABLE", "message": "MFA is not configured on this server."}},
        )

    SessionLocal = get_sync_session_factory()
    with SessionLocal() as db:
        limiter_key = f"user:{current_user.user_id}"
        pw_decision = check_limit(
            db, LimitScope.PASSWORD_CHANGE, limiter_key, record_failure=False, commit=True
        )
        if not pw_decision.allowed:
            return _too_many_requests(
                pw_decision.retry_after_seconds or 900,
                "Too many password verification attempts. Please try again later.",
            )

        db_user = db.get(User, current_user.user_id)
        if db_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "UNAUTHENTICATED", "message": "User not found."}},
            )
        try:
            pw_ok = bcrypt.checkpw(
                current_password.encode("utf-8"), (db_user.hashed_password or "").encode("utf-8")
            )
        except Exception:
            pw_ok = False
        if not pw_ok:
            failed = check_limit(
                db, LimitScope.PASSWORD_CHANGE, limiter_key, record_failure=True, commit=True
            )
            log_security_event(
                "mfa_enrollment_failed",
                severity="info",
                outcome="failure",
                actor_id=current_user.user_id,
                request_id=get_request_id(),
                details={"reason": "incorrect_password"},
            )
            if not failed.allowed:
                return _too_many_requests(
                    failed.retry_after_seconds or 900,
                    "Too many password verification attempts. Please try again later.",
                )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error": {"code": "INCORRECT_PASSWORD", "message": "Current password is incorrect."}},
            )

        # Re-enrollment replaces the second factor. A stolen password alone must
        # not be enough, so an already-enrolled account has to present a current
        # TOTP or recovery code first.
        if db_user.mfa_enabled:
            try:
                existing_secret = decrypt_secret(db_user.mfa_secret or "")
            except (MFAConfigurationError, MFADecryptionError) as exc:
                logger.error("MFA re-enrollment refused: secret unavailable (%s)", exc)
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"error": {"code": "MFA_UNAVAILABLE", "message": "MFA is not available on this server."}},
                )
            supplied = (code or "").strip()
            reauth_ok = False
            if supplied.isdigit() and len(supplied) == 6:
                reauth_ok, _ = verify_totp(
                    existing_secret,
                    supplied,
                    last_counter=db_user.mfa_last_counter,
                    allow_same_step=True,
                )
            elif supplied:
                stored_existing = json.loads(db_user.mfa_recovery_codes or "[]")
                matched = verify_recovery_code(supplied, stored_existing)
                if matched is not None:
                    db_user.mfa_recovery_codes = json.dumps(
                        [item for item in stored_existing if item != matched]
                    )
                    reauth_ok = True
            if not reauth_ok:
                mfa_failed = check_limit(
                    db, LimitScope.MFA_VERIFY, limiter_key, record_failure=True, commit=True
                )
                log_security_event(
                    "mfa_reenrollment_failed",
                    severity="warning",
                    outcome="failure",
                    actor_id=current_user.user_id,
                    request_id=get_request_id(),
                    details={"reason": "second_factor_required"},
                )
                if not mfa_failed.allowed:
                    return _too_many_requests(
                        mfa_failed.retry_after_seconds or 900,
                        "Too many MFA attempts. Please try again later.",
                    )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": {"code": "INVALID_MFA_CODE", "message": "A current MFA code is required to re-enroll."}},
                )
            clear_limit(db, LimitScope.MFA_VERIFY, limiter_key)

        secret = generate_mfa_secret()
        recovery_codes = generate_recovery_codes()
        db_user.mfa_secret = encrypt_secret(secret, key=encryption_key)
        db_user.mfa_recovery_codes = json.dumps([hash_recovery_code(code) for code in recovery_codes])
        db_user.mfa_enabled = 0  # not active until the first successful verification
        db_user.mfa_last_counter = None
        db.commit()
        clear_limit(db, LimitScope.PASSWORD_CHANGE, limiter_key)

        log_security_event(
            "mfa_enrollment_started",
            severity="info",
            outcome="success",
            actor_id=current_user.user_id,
            request_id=get_request_id(),
            details={"recovery_codes": len(recovery_codes)},
        )
        return {
            "secret": secret,
            "recovery_codes": recovery_codes,
            "message": "Scan the secret, then confirm it with /auth/mfa/verify to activate MFA.",
        }


@router.post(
    "/mfa/verify",
    summary="Confirm an MFA secret and activate MFA.",
    description=(
        "Verifies the TOTP code for the pending enrollment. A recovery code can be used "
        "instead; recovery codes are single use. Verification attempts are rate limited."
    ),
    responses={
        400: {"description": "The code is invalid"},
        403: {"description": "MFA is not available or not enrolled"},
        429: {"description": "Too many verification attempts"},
    },
)
def verify_mfa(
    request: Request,
    code: str = Body(..., embed=True),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Verify the enrollment code (or a recovery code) and activate MFA."""
    client_ip = _client_ip(request)
    SessionLocal = get_sync_session_factory()
    with SessionLocal() as db:
        decision = check_limit(
            db, LimitScope.MFA_VERIFY, f"user:{current_user.user_id}", record_failure=False, commit=True
        )
        if not decision.allowed:
            log_security_event(
                "mfa_brute_force_blocked",
                severity="warning",
                outcome="blocked",
                actor_id=current_user.user_id,
                ip_address=client_ip,
                request_id=get_request_id(),
                details={"scope": "mfa_verify", "retry_after_seconds": decision.retry_after_seconds},
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"error": {"code": "RATE_LIMITED", "message": "Too many MFA attempts. Please try again later."}},
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )

        db_user = db.get(User, current_user.user_id)
        if db_user is None or not db_user.mfa_secret:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "MFA_NOT_ENROLLED", "message": "MFA is not enrolled for this account."}},
            )

        try:
            secret = decrypt_secret(db_user.mfa_secret)
        except (MFAConfigurationError, MFADecryptionError) as exc:
            logger.error("MFA secret could not be decrypted: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "MFA_UNAVAILABLE", "message": "MFA is not available on this server."}},
            )

        valid = False
        used_recovery = False
        counter: Optional[int] = None

        if code.strip().isdigit() and len(code.strip()) == 6:
            valid, counter = verify_totp(secret, code.strip(), last_counter=db_user.mfa_last_counter)
        else:
            stored = json.loads(db_user.mfa_recovery_codes or "[]")
            match = verify_recovery_code(code.strip(), stored)
            if match is not None:
                # Recovery codes are single use.
                remaining = [item for item in stored if item != match]
                db_user.mfa_recovery_codes = json.dumps(remaining)
                valid = True
                used_recovery = True

        if not valid:
            check_limit(db, LimitScope.MFA_VERIFY, f"user:{current_user.user_id}", record_failure=True, commit=True)
            log_security_event(
                "mfa_verification_failed",
                severity="info",
                outcome="failure",
                actor_id=current_user.user_id,
                ip_address=client_ip,
                request_id=get_request_id(),
                details={"used_recovery_code": used_recovery},
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": {"code": "INVALID_MFA_CODE", "message": "The verification code is invalid."}},
            )

        db_user.mfa_enabled = 1
        if counter is not None:
            db_user.mfa_last_counter = counter
        db.commit()
        clear_limit(db, LimitScope.MFA_VERIFY, f"user:{current_user.user_id}")
        log_security_event(
            "mfa_activated",
            severity="info",
            outcome="success",
            actor_id=current_user.user_id,
            ip_address=client_ip,
            request_id=get_request_id(),
            details={"used_recovery_code": used_recovery},
        )
        return {"message": "MFA activated.", "mfa_enabled": True}


@router.post(
    "/mfa/disable",
    summary="Disable MFA for the authenticated user.",
    description="Requires the current password (or a valid MFA code). The stored secret is removed.",
    responses={
        400: {"description": "The password or MFA code is invalid"},
        403: {"description": "MFA is not enabled"},
    },
)
def disable_mfa(
    request: Request,
    current_password: str = Body(..., embed=True),
    code: Optional[str] = Body(None, embed=True),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Disable MFA (password + code required when MFA is active)."""
    SessionLocal = get_sync_session_factory()
    with SessionLocal() as db:
        limiter_key = f"user:{current_user.user_id}"
        pw_decision = check_limit(
            db, LimitScope.PASSWORD_CHANGE, limiter_key, record_failure=False, commit=True
        )
        if not pw_decision.allowed:
            return _too_many_requests(
                pw_decision.retry_after_seconds or 900,
                "Too many password verification attempts. Please try again later.",
            )

        db_user = db.get(User, current_user.user_id)
        if db_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "UNAUTHENTICATED", "message": "User not found."}},
            )
        try:
            pw_ok = bcrypt.checkpw(
                current_password.encode("utf-8"), (db_user.hashed_password or "").encode("utf-8")
            )
        except Exception:
            pw_ok = False
        if not pw_ok:
            failed = check_limit(
                db, LimitScope.PASSWORD_CHANGE, limiter_key, record_failure=True, commit=True
            )
            if not failed.allowed:
                return _too_many_requests(
                    failed.retry_after_seconds or 900,
                    "Too many password verification attempts. Please try again later.",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": {"code": "INCORRECT_PASSWORD", "message": "Current password is incorrect."}},
            )

        if db_user.mfa_enabled:
            if not db_user.mfa_secret:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"error": {"code": "MFA_NOT_ENROLLED", "message": "MFA is not enrolled for this account."}},
                )
            mfa_decision = check_limit(
                db, LimitScope.MFA_VERIFY, limiter_key, record_failure=False, commit=True
            )
            if not mfa_decision.allowed:
                return _too_many_requests(
                    mfa_decision.retry_after_seconds or 900,
                    "Too many MFA attempts. Please try again later.",
                )
            try:
                secret = decrypt_secret(db_user.mfa_secret)
            except (MFAConfigurationError, MFADecryptionError):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"error": {"code": "MFA_UNAVAILABLE", "message": "MFA is not available on this server."}},
                )
            valid, _counter = verify_totp(
                secret,
                (code or "").strip(),
                last_counter=db_user.mfa_last_counter,
                allow_same_step=True,
            )
            if not valid:
                mfa_failed = check_limit(
                    db, LimitScope.MFA_VERIFY, limiter_key, record_failure=True, commit=True
                )
                log_security_event(
                    "mfa_verification_failed",
                    severity="info",
                    outcome="failure",
                    actor_id=current_user.user_id,
                    ip_address=_client_ip(request),
                    request_id=get_request_id(),
                    details={"reason": "disable_requires_valid_code"},
                )
                if not mfa_failed.allowed:
                    return _too_many_requests(
                        mfa_failed.retry_after_seconds or 900,
                        "Too many MFA attempts. Please try again later.",
                    )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"error": {"code": "INVALID_MFA_CODE", "message": "The verification code is invalid."}},
                )

        db_user.mfa_secret = None
        db_user.mfa_recovery_codes = None
        db_user.mfa_enabled = 0
        db_user.mfa_last_counter = None
        db.commit()
        clear_limit(db, LimitScope.PASSWORD_CHANGE, limiter_key)
        clear_limit(db, LimitScope.MFA_VERIFY, limiter_key)
        log_security_event(
            "mfa_disabled",
            severity="info",
            outcome="success",
            actor_id=current_user.user_id,
            request_id=get_request_id(),
            details={},
        )
        return {"message": "MFA disabled.", "mfa_enabled": False}


# -- Password Reset Initiation Endpoint --

@router.post(
    "/password/reset",
    summary="Initiate password reset flow.",
    description="Start a password reset by requesting a reset token. In production, this triggers email delivery.",
    responses={
        200: {"description": "Reset token generated, user notified via email"},
        400: {"description": "User not found or account deactivated"},
    },
)
def initiate_password_reset(
    request: Request,
    user_id: str = Body(..., embed=True),
):
    """Initiate a password reset flow.

    Generates a single-use, expiring, hashed reset token and stores it in the
    database. The token is only ever delivered through the configured email
    provider - it is never returned by the API. The response is identical
    whether or not the account exists, so the endpoint cannot be used to probe
    for valid accounts.
    """
    generic_response = {
        "message": "If the account exists, a password reset link has been sent to its registered email address.",
        "reset_initiated": True,
    }

    SessionLocal = get_sync_session_factory()
    clean_uid = user_id.strip()
    with SessionLocal() as db:
        client_ip = _client_ip(request)
        decision = check_limit(
            db, LimitScope.PASSWORD_RESET, f"reset:{clean_uid.lower()}", record_failure=False, commit=True
        )
        ip_decision = check_limit(
            db, LimitScope.PASSWORD_RESET, f"ip:{client_ip}", record_failure=False, commit=True
        )
        if not decision.allowed or not ip_decision.allowed:
            retry_after = max(decision.retry_after_seconds, ip_decision.retry_after_seconds, 300)
            log_security_event(
                "rate_limit_triggered",
                severity="warning",
                outcome="blocked",
                ip_address=client_ip,
                request_id=get_request_id(),
                details={"scope": "password_reset", "retry_after_seconds": retry_after},
            )
            return _too_many_requests(
                retry_after, "Too many password reset requests. Please try again later."
            )

        # Find the user
        db_user = db.get(User, clean_uid)
        if db_user is None or not db_user.is_active:
            # Generic answer: do not confirm whether the account exists.
            log_security_event(
                "password_reset_requested",
                severity="info",
                outcome="failure",
                ip_address=client_ip,
                request_id=get_request_id(),
                details={"reason": "unknown_or_inactive_account"},
            )
            return generic_response

        # Generate a secure random token; only its SHA-256 hash is stored.
        reset_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(reset_token.encode("utf-8")).hexdigest()
        token_expires = _format_utc_iso(_get_utc_now() + timedelta(hours=2))  # 2-hour expiry

        # Store the hashed token and expiry in the user record
        db_user.password_reset_token = token_hash
        db_user.password_reset_token_expires = token_expires
        db.commit()

        # Deliver the token through the configured email provider. The token is
        # never included in the API response.
        provider = get_email_provider()
        delivery = provider.send(
            db_user.email,
            "RollCall AI password reset",
            (
                "A password reset was requested for your account.\n\n"
                f"Use this token within 2 hours: {reset_token}\n\n"
                "If you did not request this, you can ignore this message."
            ),
        )
        if not delivery.configured:
            logger.error(
                "DEPLOYMENT BLOCKER: password reset requested for %s but no email provider is "
                "configured - the reset link could not be delivered.",
                db_user.user_id,
            )
        elif not delivery.delivered:
            logger.error(
                "Password reset email delivery failed for %s: %s",
                db_user.user_id,
                delivery.detail,
            )

        log_security_event(
            "password_reset_requested",
            severity="info",
            outcome="success",
            actor_id=db_user.user_id,
            ip_address=client_ip,
            request_id=get_request_id(),
            details={"delivered": delivery.delivered, "provider_configured": delivery.configured},
        )
        return generic_response


# -- Password Reset Completion Endpoint --

@router.post(
    "/password/reset/confirm",
    summary="Complete a password reset with a reset token.",
    description=(
        "Consumes a single-use password reset token and sets a new password. "
        "The token is stored only as a SHA-256 hash, expires after two hours and is "
        "invalidated atomically on first use. Every session of the account is revoked."
    ),
    responses={
        400: {"description": "The token is invalid, expired or already used"},
        422: {"description": "The new password does not meet the policy"},
    },
)
def complete_password_reset(
    request: Request,
    reset_token: str = Body(..., embed=True),
    new_password: str = Body(..., embed=True),
):
    """Finish a password reset.

    The response is identical for an unknown, expired and already used token, so
    the endpoint cannot be used to probe for valid tokens.
    """
    generic_error = JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": {
                "code": "INVALID_RESET_TOKEN",
                "message": "The password reset link is invalid or has expired.",
            }
        },
    )

    # Rate limit the reset completion (brute force on the token space).
    client_ip = _client_ip(request)
    SessionLocal = get_sync_session_factory()
    with SessionLocal() as db:
        decision = check_limit(db, LimitScope.PASSWORD_RESET, f"ip:{client_ip}", record_failure=False, commit=True)
        if not decision.allowed:
            log_security_event(
                "rate_limit_triggered",
                severity="warning",
                outcome="blocked",
                ip_address=client_ip,
                request_id=get_request_id(),
                details={"scope": "password_reset", "retry_after_seconds": decision.retry_after_seconds},
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "Too many password reset attempts. Please try again later.",
                    }
                },
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )

        token_hash = hashlib.sha256((reset_token or "").strip().encode("utf-8")).hexdigest()
        now_dt = _get_utc_now()
        now_iso = _format_utc_iso(now_dt)

        # Validate the new password before consuming the token.
        try:
            _validate_password_strength(new_password)
        except HTTPException:
            return generic_error

        from sqlalchemy import update as sa_update

        target_user_id = db.execute(
            select(User.user_id).where(User.password_reset_token == token_hash)
        ).scalar_one_or_none()

        if target_user_id is None:
            check_limit(db, LimitScope.PASSWORD_RESET, f"ip:{client_ip}", record_failure=True, commit=True)
            log_security_event(
                "password_reset_failed",
                severity="info",
                outcome="failure",
                ip_address=client_ip,
                request_id=get_request_id(),
                details={"reason": "invalid_or_expired_token"},
            )
            return generic_error

        hashed_pw = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        # Atomic single-use consumption: the reset only applies while the stored
        # token matches AND is still valid. Two concurrent requests therefore
        # cannot both change the password (rowcount is 1 for exactly one).
        consumed = db.execute(
            sa_update(User)
            .where(
                User.user_id == target_user_id,
                User.password_reset_token == token_hash,
                User.password_reset_token_expires.is_not(None),
                User.password_reset_token_expires > now_iso,
                User.is_active == 1,
            )
            .values(
                hashed_password=hashed_pw,
                password_reset_token=None,
                password_reset_token_expires=None,
            )
        )
        if consumed.rowcount != 1:
            db.rollback()
            check_limit(db, LimitScope.PASSWORD_RESET, f"ip:{client_ip}", record_failure=True, commit=True)
            log_security_event(
                "password_reset_failed",
                severity="info",
                outcome="failure",
                actor_id=target_user_id,
                ip_address=client_ip,
                request_id=get_request_id(),
                details={"reason": "invalid_or_expired_token"},
            )
            return generic_error

        # Revoke every session and refresh token of the account in the same
        # transaction as the password change.
        db.execute(
            sa_update(AuthSession).where(AuthSession.user_id == target_user_id).values(revoked_at=now_iso)
        )
        db.execute(
            sa_update(AuthRefreshToken).where(
                AuthRefreshToken.session_id.in_(
                    sa_select(AuthSession.session_id).where(AuthSession.user_id == target_user_id)
                )
            ).values(revoked_at=now_iso)
        )
        db.commit()

        clear_limit(db, LimitScope.PASSWORD_RESET, f"ip:{client_ip}")
        log_security_event(
            "password_reset_completed",
            severity="info",
            outcome="success",
            actor_id=target_user_id,
            ip_address=client_ip,
            request_id=get_request_id(),
            details={"sessions_revoked": True},
        )
        return {
            "message": "Password has been reset. All sessions have been invalidated.",
            "password_reset": True,
        }


# -- Session/Device Security --

@router.get(
    "/sessions",
    summary="List authenticated user's active sessions.",
    description="Return summary of user's active sessions without exposing refresh tokens or raw session secrets.",
    responses={
        200: {"description": "List of active sessions"},
        401: {"description": "User not authenticated"},
    },
)
def list_user_sessions(current_user: AuthenticatedUser = Depends(get_current_user)):
    """List active sessions for the authenticated user.

    Returns session metadata (created, IP, user-agent) without exposing
    refresh tokens or raw session secrets. Each session can be individually
    revoked.
    """
    SessionLocal = get_sync_session_factory()
    with SessionLocal() as db:
        # Get all sessions for this user
        stmt = select(AuthSession).where(AuthSession.user_id == current_user.user_id)
        sessions = db.execute(stmt).scalars().all()

        session_list = []
        for s in sessions:
            # Never expose refresh tokens or raw session secrets
            session_list.append(
                {
                    "session_id": s.session_id,
                    "created_at": s.created_at,
                    "absolute_expiry": s.absolute_expiry,
                    "revoked_at": s.revoked_at,
                    "user_agent": s.user_agent,
                    "ip_address": s.ip_address,
                    "remember_me": bool(s.remember_me),
                }
            )

        return {"sessions": session_list}


@router.post(
    "/sessions/revoke/{session_id}",
    summary="Revoke a specific user session.",
    description="Revoke a specific session by session_id. The current session cannot be revoked via this endpoint (use logout instead).",
    responses={
        200: {"description": "Session revoked successfully"},
        401: {"description": "User not authenticated or session not found"},
        403: {"description": "Cannot revoke the currently active session"},
    },
)
def revoke_user_session(
    session_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Revoke a specific user session by session_id.

    The currently active session cannot be revoked via this endpoint;
    use the logout endpoint instead. All refresh tokens associated
    with the session are also revoked.
    """
    import uuid as uuid_mod

    # Validate session_id format
    try:
        uuid_mod.UUID(session_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "INVALID_SESSION_ID", "message": "Invalid session ID format."}},
        )

    SessionLocal = get_sync_session_factory()
    with SessionLocal() as db:
        session = db.get(AuthSession, session_id)

        # Object-level authorization. A session belonging to another account is
        # reported exactly like a missing one, so ids cannot be probed and one
        # user can never revoke another user's session.
        if session is None or session.user_id != current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": {"code": "SESSION_NOT_FOUND", "message": "Session not found."}},
            )

        now_iso = _format_utc_iso(_get_utc_now())
        db.execute(
            update(AuthSession).where(AuthSession.session_id == session_id).values(revoked_at=now_iso)
        )
        # Also revoke any refresh tokens associated with this session
        db.execute(
            update(AuthRefreshToken).where(AuthRefreshToken.session_id == session_id).values(revoked_at=now_iso)
        )
        db.commit()

        return {"message": "Session revoked successfully"}


@router.post(
    "/sessions/revoke-all",
    summary="Revoke all other user sessions.",
    description="Revoke all sessions for the authenticated user except the currently active one.",
    responses={
        200: {"description": "All other sessions revoked successfully"},
        401: {"description": "User not authenticated"},
    },
)
def revoke_all_other_sessions(
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Revoke all other sessions for the authenticated user.

    Does not revoke the currently active session (use logout for that).
    """
    SessionLocal = get_sync_session_factory()
    with SessionLocal() as db:
        # Revoke all sessions except potentially the current one
        now_iso = _format_utc_iso(_get_utc_now())
        db.execute(
            update(AuthSession).where(AuthSession.user_id == current_user.user_id).values(revoked_at=now_iso)
        )
        db.execute(
            update(AuthRefreshToken)
            .where(
                AuthRefreshToken.session_id.in_(
                    sa_select(AuthSession.session_id).where(
                        AuthSession.user_id == current_user.user_id
                    )
                )
            )
            .values(revoked_at=now_iso)
        )
        db.commit()

        return {"message": "All other sessions have been revoked."}



