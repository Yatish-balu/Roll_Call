"""Authentication, JWT issuance, rate limiting, and RBAC tests for RollCall AI Wave 1 Prompt N2."""

import concurrent.futures
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import bcrypt
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker, Session as SqlSession

from app.auth.jwt import (
    create_access_token,
    decode_and_verify_token,
    get_local_jwt_secret,
    validate_jwt_secret_configuration,
    AuthenticationError,
)
from app.db.base import Base
from app.db.models import LoginAttempt, TeacherSubject, User
from app.main import app
from scripts.seed_users import seed_users

TEST_JWT_SECRET = "test-secret-key-that-is-at-least-32-bytes-long-for-testing"
TEST_ADMIN_KEY = "test-admin-secret-key-secure"


@pytest.fixture
def auth_test_db(monkeypatch):
    """
    Provide an isolated, clean SQLite database for authentication testing.
    Patches DB connection factory and environment variables.
    """
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "auth_test.db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(bind=engine, class_=SqlSession, expire_on_commit=False)

    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("ADMIN_KEY", TEST_ADMIN_KEY)
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setattr("app.db.connection.get_sync_session_factory", lambda eng=None: SessionLocal)
    monkeypatch.setattr("app.routers.auth.get_sync_session_factory", lambda: SessionLocal)

    # Pre-seed a known active FACULTY and ADMIN user
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with SessionLocal() as db:
        faculty_pw = bcrypt.hashpw(b"FacultyPass123!", bcrypt.gensalt()).decode("utf-8")
        admin_pw = bcrypt.hashpw(b"AdminPass123!", bcrypt.gensalt()).decode("utf-8")

        f_user = User(
            user_id="teacher_jane",
            email="jane@school.edu",
            role="FACULTY",
            hashed_password=faculty_pw,
            is_active=1,
            created_at=now_iso,
        )
        a_user = User(
            user_id="admin_john",
            email="john@school.edu",
            role="ADMIN",
            hashed_password=admin_pw,
            is_active=1,
            created_at=now_iso,
        )
        legacy_user = User(
            user_id="legacy",
            email="legacy@rollcall.internal",
            role="ADMIN",
            hashed_password=None,
            is_active=0,
            created_at=now_iso,
        )
        rate_user = User(
            user_id="rate_limit_test_user",
            email="rate@school.edu",
            role="FACULTY",
            hashed_password=faculty_pw,
            is_active=1,
            created_at=now_iso,
        )
        concurrent_user = User(
            user_id="concurrent_dos_user",
            email="dos@school.edu",
            role="FACULTY",
            hashed_password=faculty_pw,
            is_active=1,
            created_at=now_iso,
        )
        db.add_all([f_user, a_user, legacy_user, rate_user, concurrent_user])
        db.flush()

        ts1 = TeacherSubject(user_id="teacher_jane", subject_code="ML")
        ts2 = TeacherSubject(user_id="teacher_jane", subject_code="DIST-SYS")
        db.add_all([ts1, ts2])
        db.commit()

    # Route sessions and the auth user lookup share the request-scoped session,
    # so point get_db at this isolated database too.
    from app.dependencies import get_db

    def override_get_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db

    yield engine, SessionLocal

    if previous_override is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous_override
    engine.dispose()
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def client(auth_test_db):
    return TestClient(app)


def test_admin_login_with_admin_key_success_and_failures(client, auth_test_db):
    """
    Regression test for the ADMIN-key login flow:

    * an ADMIN account with ``mfa_enabled = 0`` must never be blocked by the
      MFA branch, and
    * ``admin_key`` must be accepted after client/server-side whitespace
      trimming (the path used by the React login form) while missing and
      mismatched keys fail closed with 401.
    """
    _, SessionLocal = auth_test_db
    with SessionLocal() as db:
        admin = db.get(User, "admin_john")
        assert admin is not None
        assert admin.mfa_enabled in (0, None)  # MFA must not gate this login

    correct_key = TEST_ADMIN_KEY

    # 1. Valid admin_key -> 200 with an ADMIN token.
    ok = client.post(
        "/api/v1/auth/login",
        json={"user_id": "admin_john", "password": "AdminPass123!", "admin_key": correct_key},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["role"] == "ADMIN"
    verified = decode_and_verify_token(ok.json()["token"], secret=TEST_JWT_SECRET)
    assert verified.user_id == "admin_john"

    # 2. Whitespace-padded admin_key -> still 200 (matches backend trimming).
    padded = client.post(
        "/api/v1/auth/login",
        json={"user_id": "admin_john", "password": "AdminPass123!", "admin_key": f"  {correct_key}  "},
    )
    assert padded.status_code == 200, padded.text
    assert padded.json()["role"] == "ADMIN"

    # 3. Missing admin_key -> 401 generic error.
    missing = client.post(
        "/api/v1/auth/login",
        json={"user_id": "admin_john", "password": "AdminPass123!"},
    )
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "UNAUTHORIZED"

    # 4. Mismatched admin_key -> 401 generic error.
    mismatch = client.post(
        "/api/v1/auth/login",
        json={"user_id": "admin_john", "password": "AdminPass123!", "admin_key": f"{correct_key}-typo"},
    )
    assert mismatch.status_code == 401
    assert mismatch.json()["error"]["code"] == "UNAUTHORIZED"


def test_login_success_with_valid_credentials(client):
    """Test 1: Correct credentials return HTTP 200, signed token, role, and subject codes."""
    res = client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_jane", "password": "FacultyPass123!"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "token" in data
    assert data["role"] == "FACULTY"
    assert "ML" in data["subject_codes"]
    assert "DIST-SYS" in data["subject_codes"]
    assert "expires_at_utc" in data

    # Verify token payload
    verified = decode_and_verify_token(data["token"], secret=TEST_JWT_SECRET)
    assert verified.user_id == "teacher_jane"
    assert verified.role.value == "FACULTY"


def test_login_fails_with_wrong_password(client):
    """Test 2: Wrong password returns HTTP 401 with generic error message."""
    res = client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_jane", "password": "IncorrectPassword!"},
    )
    assert res.status_code == 401
    data = res.json()
    assert data["error"]["code"] == "UNAUTHORIZED"
    assert "Invalid user ID or password" in data["error"]["message"]


def test_login_fails_with_unknown_user(client):
    """Test 3: Unknown user returns the exact same generic HTTP 401 message (no enumeration)."""
    res = client.post(
        "/api/v1/auth/login",
        json={"user_id": "nonexistent_ghost_user", "password": "AnyPassword123!"},
    )
    assert res.status_code == 401
    data = res.json()
    assert data["error"]["code"] == "UNAUTHORIZED"
    assert "Invalid user ID or password" in data["error"]["message"]


def test_access_with_expired_token_returns_401(client):
    """Test 4: Expired token returns HTTP 401."""
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    expired_token = create_access_token(
        {"sub": "teacher_jane", "role": "FACULTY"},
        expires_delta=timedelta(seconds=-10),
        secret=TEST_JWT_SECRET,
    )
    res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert res.status_code == 401
    assert "expired" in res.json()["detail"].lower()


def test_access_with_tampered_token_returns_401(client):
    """Test 5: Tampered or invalidly signed token returns HTTP 401."""
    token = create_access_token(
        {"sub": "teacher_jane", "role": "FACULTY"},
        secret="different-secret-key-32bytes-min-sample",
    )
    res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401
    assert "verification failed" in res.json()["detail"].lower() or "invalid" in res.json()["detail"].lower()


def test_modified_role_claim_cannot_grant_privileges(client):
    """Test 6: Token role tampering cannot grant unassigned privileges (DB is authoritative)."""
    # Forge a token claiming role=ADMIN for a user who is FACULTY in the database
    forged_token = create_access_token(
        {"sub": "teacher_jane", "role": "ADMIN"},
        secret=TEST_JWT_SECRET,
    )
    res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {forged_token}"},
    )
    assert res.status_code == 200
    # Must report FACULTY (authoritative from DB), NOT ADMIN!
    assert res.json()["role"] == "FACULTY"


def test_admin_login_requires_valid_admin_key(client):
    """Test 7: ADMIN login fails closed if ADMIN_KEY is missing, empty, or mismatched."""
    # 1. Missing admin_key -> 401
    res1 = client.post(
        "/api/v1/auth/login",
        json={"user_id": "admin_john", "password": "AdminPass123!"},
    )
    assert res1.status_code == 401
    assert res1.json()["error"]["code"] == "UNAUTHORIZED"

    # 2. Empty admin_key -> 401
    res2 = client.post(
        "/api/v1/auth/login",
        json={"user_id": "admin_john", "password": "AdminPass123!", "admin_key": ""},
    )
    assert res2.status_code == 401

    # 3. Wrong admin_key -> 401
    res3 = client.post(
        "/api/v1/auth/login",
        json={"user_id": "admin_john", "password": "AdminPass123!", "admin_key": "wrong-key"},
    )
    assert res3.status_code == 401

    # 4. Correct admin_key -> 200
    res4 = client.post(
        "/api/v1/auth/login",
        json={"user_id": "admin_john", "password": "AdminPass123!", "admin_key": TEST_ADMIN_KEY},
    )
    assert res4.status_code == 200
    assert res4.json()["role"] == "ADMIN"


def test_database_login_rate_limiting_triggers_429(client):
    """Test 8: Five failed attempts in rolling 10 minutes allow, 6th returns HTTP 429 RATE_LIMITED."""
    target_user = "rate_limit_test_user"

    # Attempts 1 through 5: Fail with 401
    for i in range(5):
        res = client.post(
            "/api/v1/auth/login",
            json={"user_id": target_user, "password": f"WrongAttempt{i}"},
        )
        assert res.status_code == 401, f"Attempt {i+1} expected 401, got {res.status_code}"

    # Attempt 6: Blocked by rate limiter -> 429
    res6 = client.post(
        "/api/v1/auth/login",
        json={"user_id": target_user, "password": "WrongAttempt6"},
    )
    assert res6.status_code == 429
    data = res6.json()
    assert data["error"]["code"] == "RATE_LIMITED"
    assert "Too many failed login attempts" in data["error"]["message"]
    assert res6.headers.get("Retry-After") == "600"


def test_deactivated_user_cannot_access_or_login(client, auth_test_db):
    """Test 9: Deactivated user (is_active=0) cannot log in, and valid token is rejected with 401."""
    engine, SessionLocal = auth_test_db

    # Deactivate teacher_jane
    with SessionLocal() as db:
        user = db.get(User, "teacher_jane")
        user.is_active = 0
        db.commit()

    # 1. Login attempt fails with generic 401
    res_login = client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_jane", "password": "FacultyPass123!"},
    )
    assert res_login.status_code == 401
    assert res_login.json()["error"]["code"] == "UNAUTHORIZED"

    # 2. Existing valid token rejected immediately on /auth/me
    token = create_access_token({"sub": "teacher_jane", "role": "FACULTY"}, secret=TEST_JWT_SECRET)
    res_me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_me.status_code == 401
    assert "deactivated" in res_me.json()["detail"].lower()


def test_jwt_secret_validation_rejects_missing_or_short_secret():
    """Test 10: Missing or shorter than 32 characters JWT_SECRET fails configuration validation."""
    # Missing / empty secret
    with pytest.raises(ValueError) as exc1:
        validate_jwt_secret_configuration(secret="")
    assert "missing or empty" in str(exc1.value).lower()

    # Secret < 32 characters
    with pytest.raises(ValueError) as exc2:
        validate_jwt_secret_configuration(secret="too-short-secret-key-16b")
    assert "too short" in str(exc2.value).lower()

    # Valid secret >= 32 characters returns clean secret
    valid_secret = "a-very-secure-and-long-enough-secret-key-32+"
    assert validate_jwt_secret_configuration(secret=valid_secret) == valid_secret


def test_legacy_user_cannot_login(client):
    """Test 11: The legacy sentinel user has NULL password and cannot authenticate under any input."""
    for trial_pw in ["", "legacy", "LEGACY_NO_LOGIN", "admin"]:
        res = client.post(
            "/api/v1/auth/login",
            json={"user_id": "legacy", "password": trial_pw, "admin_key": TEST_ADMIN_KEY},
        )
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"


def test_supabase_jwt_verification_compatibility(client, monkeypatch):
    """Test 12: Existing Supabase JWT verification remains functional alongside local secret."""
    supabase_secret = "supabase-shared-secret-key-32bytes-minimum"
    monkeypatch.setenv("SUPABASE_JWT_SECRET", supabase_secret)

    # Issue a token signed with the Supabase secret
    supabase_token = jwt.encode(
        {
            "sub": "supabase_user_123",
            "email": "supabase@cloud.internal",
            "role": "authenticated",
            "app_metadata": {"role": "FACULTY"},
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
            "iat": int(datetime.now(timezone.utc).timestamp()),
        },
        supabase_secret,
        algorithm="HS256",
    )

    # Access endpoint with Supabase token
    res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {supabase_token}"},
    )
    assert res.status_code == 200
    assert res.json()["user_id"] == "supabase_user_123"
    assert res.json()["role"] == "FACULTY"


def test_login_attempts_recorded_in_database(client, auth_test_db):
    """Test 13: Both successful and failed login attempts are persistently logged in login_attempts."""
    engine, SessionLocal = auth_test_db

    # 1. Trigger failed login
    client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_jane", "password": "WrongPassword"},
    )
    # 2. Trigger successful login
    client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_jane", "password": "FacultyPass123!"},
    )

    with SessionLocal() as db:
        attempts = db.execute(
            select(LoginAttempt).where(LoginAttempt.user_id == "teacher_jane").order_by(LoginAttempt.id.desc())
        ).scalars().all()
        assert len(attempts) >= 2
        # Latest was success (1)
        assert attempts[0].success == 1
        # Previous was failure (0)
        assert attempts[1].success == 0


def test_seed_users_script_is_idempotent(auth_test_db):
    """Test 14: Re-running seed_users does not duplicate records or overwrite passwords unexpectedly."""
    engine, SessionLocal = auth_test_db

    # Run seed script first time
    res1 = seed_users(session_factory=SessionLocal)
    assert res1["created"] > 0

    # Capture password hash of seeded admin
    with SessionLocal() as db:
        admin_first = db.get(User, "admin_root")
        assert admin_first is not None
        first_hash = admin_first.hashed_password

    # Run seed script second time -> must skip all without changes
    res2 = seed_users(session_factory=SessionLocal)
    assert res2["created"] == 0
    assert res2["skipped"] >= 4

    with SessionLocal() as db:
        admin_second = db.get(User, "admin_root")
        assert admin_second.hashed_password == first_hash


def test_concurrent_login_rate_limiting_cannot_be_bypassed(client):
    """Test 15: Simultaneous concurrent login requests cannot bypass the 5-attempt rate limit."""
    target_user = "concurrent_dos_user"

    def do_bad_login(attempt_idx: int):
        return client.post(
            "/api/v1/auth/login",
            json={"user_id": target_user, "password": f"InvalidPassword_{attempt_idx}"},
        )

    # Fire 12 simultaneous threads targeting the same user ID
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(do_bad_login, i) for i in range(12)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    status_codes = [r.status_code for r in results]
    count_401 = status_codes.count(401)
    count_429 = status_codes.count(429)

    # Exactly 5 failed attempts allowed; the remaining 7 must be rejected with 429
    assert count_401 == 5, f"Expected exactly 5 HTTP 401s, got {count_401}. Results: {status_codes}"
    assert count_429 == 7, f"Expected exactly 7 HTTP 429s, got {count_429}. Results: {status_codes}"

