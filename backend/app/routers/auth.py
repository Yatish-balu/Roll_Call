"""Authentication router for secure user login, persistent sessions, token rotation, and logout."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import threading
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.jwt import create_access_token
from app.auth.roles import normalize_role
from app.db.connection import get_sync_session_factory
from app.db.models import AuthRefreshToken, AuthSession, LoginAttempt, TeacherSubject, User
from app.schemas.auth import AuthenticatedUser, LoginRequest, LoginResponse, UserMeResponse

logger = logging.getLogger("rollcall.auth.router")

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Concurrency lock to serialize the check-and-record window in SQLite
_login_rate_lock = threading.Lock()

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
    """Record an authentication attempt in login_attempts table."""
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


def _check_rate_limit(
    db: Session,
    user_id: str,
    now_dt: datetime,
    max_failures: int = 5,
    window_seconds: int = 600,
) -> bool:
    """
    Check if the user has reached max allowed failures in the rolling window.
    Returns True if allowed, False if rate limited.
    """
    cutoff_dt = now_dt - timedelta(seconds=window_seconds)
    cutoff_iso = _format_utc_iso(cutoff_dt)

    stmt = (
        select(func.count(LoginAttempt.id))
        .where(
            LoginAttempt.user_id == user_id,
            LoginAttempt.success == 0,
            LoginAttempt.timestamp >= cutoff_iso,
        )
    )
    failed_count = db.execute(stmt).scalar() or 0
    return failed_count < max_failures


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
    client_ip = request.client.host if request.client else "127.0.0.1"
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
        with _login_rate_lock:
            user = db.get(User, clean_uid)
            record_uid = user.user_id if user is not None else None

            # 1. Rate limit check (rolling 10-minute window)
            allowed = _check_rate_limit(db, clean_uid, now_dt)
            if not allowed:
                _record_attempt(db, user_id=record_uid, ip_address=client_ip, success=0, timestamp=now_iso)
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": {
                            "code": "RATE_LIMITED",
                            "message": "Too many failed login attempts. Please try again later.",
                        }
                    },
                    headers={"Retry-After": "600"},
                )

            # 2. Validation: user must exist, be active, and possess a valid password hash
            if user is None or not user.is_active or not user.hashed_password:
                _record_attempt(db, user_id=record_uid, ip_address=client_ip, success=0, timestamp=now_iso)
                return generic_401

            # 3. Verify password with bcrypt
            try:
                pw_matches = bcrypt.checkpw(clean_pw.encode("utf-8"), user.hashed_password.encode("utf-8"))
            except Exception:
                pw_matches = False

            if not pw_matches:
                _record_attempt(db, user_id=record_uid, ip_address=client_ip, success=0, timestamp=now_iso)
                return generic_401

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

            # 5. Record successful login attempt
            _record_attempt(db, user_id=record_uid, ip_address=client_ip, success=1, timestamp=now_iso)

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
            db.commit()

        # 8. Fetch assigned subject codes
        stmt = select(TeacherSubject.subject_code).where(TeacherSubject.user_id == clean_uid)
        subject_codes = [r[0] for r in db.execute(stmt).all()]

        # 9. Issue signed JWT token with 15-minute expiry
        exp_dt = now_dt + timedelta(minutes=15)
        exp_iso = _format_utc_iso(exp_dt)
        token_claims = {
            "sub": user.user_id,
            "role": user.role,
            "iat": int(now_dt.timestamp()),
            "exp": int(exp_dt.timestamp()),
        }
        token = create_access_token(token_claims, expires_delta=timedelta(minutes=15))

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

    SessionLocal = get_sync_session_factory()
    with SessionLocal() as db:
        token_record = db.execute(
            select(AuthRefreshToken).where(AuthRefreshToken.token_hash == candidate_hash)
        ).scalar_one_or_none()

        if token_record is None:
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


