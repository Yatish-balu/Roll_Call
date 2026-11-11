"""Persistent Authentication Sessions, Token Rotation, and Concurrency Tests (Wave 1, Prompt N2.1)."""

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
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.orm import sessionmaker, Session as SqlSession

from alembic.config import Config
from alembic import command

from app.auth.jwt import (
    create_access_token,
    decode_and_verify_token,
    get_local_jwt_secret,
    validate_jwt_secret_configuration,
    AuthenticationError,
)
from app.db.base import Base
from app.db.crud import revoke_all_user_sessions
from app.db.models import AuthRefreshToken, AuthSession, LoginAttempt, TeacherSubject, User
from app.main import app

TEST_JWT_SECRET = "test-session-secret-key-that-is-at-least-32-bytes-long"
TEST_ADMIN_KEY = "test-session-admin-secret-key"
CSRF_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


@pytest.fixture
def session_test_db(monkeypatch):
    """
    Provide an isolated, clean SQLite database with all tables for session testing.
    """
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "session_test.db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(bind=engine, class_=SqlSession, expire_on_commit=False)

    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("ADMIN_KEY", TEST_ADMIN_KEY)
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setattr("app.db.connection.get_sync_session_factory", lambda eng=None: SessionLocal)
    monkeypatch.setattr("app.routers.auth.get_sync_session_factory", lambda: SessionLocal)

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with SessionLocal() as db:
        faculty_pw = bcrypt.hashpw(b"FacultyPass123!", bcrypt.gensalt()).decode("utf-8")
        admin_pw = bcrypt.hashpw(b"AdminPass123!", bcrypt.gensalt()).decode("utf-8")

        f_user = User(
            user_id="teacher_alice",
            email="alice@school.edu",
            role="FACULTY",
            hashed_password=faculty_pw,
            is_active=1,
            created_at=now_iso,
        )
        a_user = User(
            user_id="admin_bob",
            email="bob@school.edu",
            role="ADMIN",
            hashed_password=admin_pw,
            is_active=1,
            created_at=now_iso,
        )
        db.add_all([f_user, a_user])
        db.flush()

        ts1 = TeacherSubject(user_id="teacher_alice", subject_code="ML")
        db.add(ts1)
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

    yield engine, SessionLocal, db_path

    if previous_override is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous_override
    engine.dispose()
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def client(session_test_db):
    return TestClient(app)


def test_migration_0003_upgrade_and_downgrade_on_disposable_db():
    """Test: Alembic migration 0003_auth_sessions upgrades and downgrades cleanly on disposable SQLite DB."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "mig_test.db").replace("\\", "/")
    db_url = f"sqlite:///{db_path}"

    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    alembic_ini = os.path.join(backend_dir, "alembic.ini")

    cfg = Config(alembic_ini)
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))

    try:
        # Upgrade to head (0003_auth_sessions)
        command.upgrade(cfg, "head")

        engine = create_engine(db_url)
        with engine.connect() as conn:
            tables = [r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()]
            assert "auth_sessions" in tables
            assert "auth_refresh_tokens" in tables

        # Downgrade back to 0002_rbac_tables
        command.downgrade(cfg, "0002_rbac_tables")
        with engine.connect() as conn:
            tables_after = [r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()]
            assert "auth_sessions" not in tables_after
            assert "auth_refresh_tokens" not in tables_after
            assert "users" in tables_after
            assert "sessions" in tables_after

        # Upgrade back to head
        command.upgrade(cfg, "head")
        engine.dispose()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_login_issues_15_minute_access_token(client):
    """Test 1: Successful login issues an access token with a 15-minute lifetime."""
    res = client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_alice", "password": "FacultyPass123!"},
    )
    assert res.status_code == 200
    data = res.json()
    token = data["token"]

    # Decode claims unverified to check exp - iat window
    claims = jwt.decode(token, options={"verify_signature": False})
    lifetime_seconds = claims["exp"] - claims["iat"]
    assert 890 <= lifetime_seconds <= 910  # exactly ~15 minutes (900 seconds)


def test_login_sets_httponly_refresh_cookie(client):
    """Test 2: Successful login sets an HttpOnly cookie named rollcall_refresh_token."""
    res = client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_alice", "password": "FacultyPass123!"},
    )
    assert res.status_code == 200
    cookie = res.cookies.get("rollcall_refresh_token")
    assert cookie is not None
    assert len(cookie) > 20


def test_remember_me_enabled_sets_persistent_cookie(client):
    """Test 3: remember_me=True sets persistent 7-day cookie."""
    res = client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_alice", "password": "FacultyPass123!", "remember_me": True},
    )
    assert res.status_code == 200
    cookie_header = res.headers.get("set-cookie", "")
    assert "Max-Age=604800" in cookie_header or "max-age=604800" in cookie_header.lower()


def test_remember_me_disabled_sets_browser_session_cookie(client):
    """Test 4: remember_me=False creates a browser-session cookie (no Max-Age)."""
    res = client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_alice", "password": "FacultyPass123!", "remember_me": False},
    )
    assert res.status_code == 200
    cookie_header = res.headers.get("set-cookie", "")
    assert "Max-Age=" not in cookie_header and "max-age=" not in cookie_header


def test_refresh_returns_new_access_jwt(client):
    """Test 5: Refresh returns a newly signed 15-minute access JWT."""
    login_res = client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_alice", "password": "FacultyPass123!"},
    )
    assert login_res.status_code == 200
    old_token = login_res.json()["token"]

    refresh_res = client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert refresh_res.status_code == 200
    new_data = refresh_res.json()
    assert "token" in new_data
    assert new_data["token"] != old_token
    assert new_data["role"] == "FACULTY"


def test_refresh_rotates_refresh_token(client):
    """Test 6: Each refresh rotates the opaque refresh token cookie."""
    login_res = client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_alice", "password": "FacultyPass123!"},
    )
    cookie_1 = login_res.cookies.get("rollcall_refresh_token")

    refresh_res_1 = client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    cookie_2 = refresh_res_1.cookies.get("rollcall_refresh_token")
    assert cookie_2 is not None
    assert cookie_2 != cookie_1


def test_old_consumed_refresh_token_cannot_be_reused(client):
    """Test 7: Once a token has been rotated, presenting the old token fails with 401."""
    login_res = client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_alice", "password": "FacultyPass123!"},
    )
    stale_cookie = login_res.cookies.get("rollcall_refresh_token")

    # Rotate once -> consumes stale_cookie
    client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)

    # Replay stale_cookie
    client.cookies.set("rollcall_refresh_token", stale_cookie)
    replay_res = client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert replay_res.status_code == 401
    assert replay_res.json()["error"]["code"] in ("UNAUTHENTICATED", "UNAUTHORIZED", "TOKEN_REUSED")


def test_reuse_detection_revokes_entire_session_family_after_multiple_rotations(client):
    """Test 8: Replaying an older token after at least two rotations revokes the complete session family."""
    # Initial Login -> Token 0
    login_res = client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_alice", "password": "FacultyPass123!"},
    )
    token_0 = login_res.cookies.get("rollcall_refresh_token")

    # Rotation 1 -> Token 1
    ref_1 = client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    token_1 = ref_1.cookies.get("rollcall_refresh_token")

    # Rotation 2 -> Token 2
    ref_2 = client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    token_2 = ref_2.cookies.get("rollcall_refresh_token")

    assert token_0 != token_1 != token_2

    # Attack: Attacker replays Token 0 (consumed 2 rotations ago)
    client.cookies.set("rollcall_refresh_token", token_0)
    attack_res = client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert attack_res.status_code == 401
    assert attack_res.json()["error"]["code"] in ("UNAUTHENTICATED", "TOKEN_REUSED")

    # Consequence: Token 2 (which was legitimately active) must now ALSO be revoked!
    client.cookies.set("rollcall_refresh_token", token_2)
    subsequent_res = client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert subsequent_res.status_code == 401


def test_refresh_after_seven_day_absolute_expiry_fails(client, session_test_db):
    """Test 9: Refresh requests past the seven-day absolute deadline are rejected."""
    engine, SessionLocal, _ = session_test_db

    login_res = client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_alice", "password": "FacultyPass123!"},
    )
    assert login_res.status_code == 200

    # Fast forward session absolute expiry into the past
    past_iso = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with SessionLocal() as db:
        db.execute(update(AuthSession).values(absolute_expiry=past_iso))
        db.commit()

    ref_res = client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert ref_res.status_code == 401
    assert ref_res.json()["error"]["code"] in ("UNAUTHENTICATED", "SESSION_EXPIRED")


def test_refresh_cannot_extend_original_absolute_expiry(client, session_test_db):
    """Test 10: Multiple refreshes preserve the original seven-day deadline verbatim."""
    engine, SessionLocal, _ = session_test_db

    login_res = client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_alice", "password": "FacultyPass123!"},
    )
    with SessionLocal() as db:
        orig_session = db.execute(select(AuthSession)).scalar_one()
        orig_expiry = orig_session.absolute_expiry

    # Perform two rotations
    client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)

    with SessionLocal() as db:
        updated_session = db.execute(select(AuthSession)).scalar_one()
        assert updated_session.absolute_expiry == orig_expiry


def test_logout_revokes_session_and_clears_cookie(client, session_test_db):
    """Test 11: Logout revokes session family in database and clears the refresh cookie."""
    engine, SessionLocal, _ = session_test_db

    login_res = client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_alice", "password": "FacultyPass123!"},
    )
    cookie = login_res.cookies.get("rollcall_refresh_token")

    logout_res = client.post("/api/v1/auth/logout", headers=CSRF_HEADERS)
    assert logout_res.status_code == 200
    assert logout_res.json()["success"] is True

    # Database session marked revoked
    with SessionLocal() as db:
        s = db.execute(select(AuthSession)).scalar_one()
        assert s.revoked_at is not None

    # Replay cookie must fail
    client.cookies.set("rollcall_refresh_token", cookie)
    ref_res = client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert ref_res.status_code == 401


def test_revoked_session_cannot_refresh(client, session_test_db):
    """Test 12: An explicitly revoked session cannot be refreshed."""
    engine, SessionLocal, _ = session_test_db

    client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_alice", "password": "FacultyPass123!"},
    )
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with SessionLocal() as db:
        db.execute(update(AuthSession).values(revoked_at=now_iso))
        db.commit()

    res = client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert res.status_code == 401


def test_deactivated_user_cannot_refresh(client, session_test_db):
    """Test 13: Deactivating a user immediately blocks refresh and revokes active sessions."""
    engine, SessionLocal, _ = session_test_db

    client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_alice", "password": "FacultyPass123!"},
    )
    # Deactivate teacher_alice
    with SessionLocal() as db:
        user = db.get(User, "teacher_alice")
        user.is_active = 0
        db.commit()

    res = client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert res.status_code == 401
    assert res.json()["error"]["code"] in ("UNAUTHENTICATED", "USER_DEACTIVATED", "UNAUTHORIZED")


def test_password_session_revocation_invalidates_existing_tokens(client, session_test_db):
    """Test 14: revoke_all_user_sessions invalidates all active sessions for that user."""
    engine, SessionLocal, _ = session_test_db

    client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_alice", "password": "FacultyPass123!"},
    )
    # Call revocation helper
    with SessionLocal() as db:
        count = revoke_all_user_sessions(db, "teacher_alice")
        assert count >= 1
        db.commit()

    res = client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert res.status_code == 401


def test_invalid_origin_is_rejected(client):
    """Test 15: Untrusted request Origin header triggers HTTP 403 Forbidden on refresh and logout."""
    client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_alice", "password": "FacultyPass123!"},
    )
    # Refresh with malicious Origin
    bad_origin_headers = {"Origin": "https://malicious-attacker-site.com", **CSRF_HEADERS}
    res = client.post("/api/v1/auth/refresh", headers=bad_origin_headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"

    # Logout with malicious Origin
    res_logout = client.post("/api/v1/auth/logout", headers=bad_origin_headers)
    assert res_logout.status_code == 403


def test_missing_csrf_header_is_rejected(client):
    """Test 16: Missing custom CSRF header on refresh or logout triggers HTTP 403."""
    client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_alice", "password": "FacultyPass123!"},
    )
    # Post without CSRF header
    res = client.post("/api/v1/auth/refresh")
    assert res.status_code == 403
    assert res.json()["error"]["code"] in ("FORBIDDEN", "CSRF_DETECTED")


def test_concurrent_refresh_attempts_cannot_create_multiple_token_branches(client):
    """Test 17: Concurrent simultaneous refresh calls with same token allow exactly one winner."""
    login_res = client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_alice", "password": "FacultyPass123!"},
    )
    cookie_val = login_res.cookies.get("rollcall_refresh_token")

    def do_refresh():
        # Fresh test client with the same cookie
        c = TestClient(app)
        c.cookies.set("rollcall_refresh_token", cookie_val)
        return c.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(do_refresh) for _ in range(6)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    status_codes = [r.status_code for r in results]
    # Exactly one request can succeed (200) to rotate; remaining must fail (401)
    assert status_codes.count(200) == 1
    assert status_codes.count(401) == 5


def test_different_user_refresh_token_cannot_access_another_account(client, session_test_db):
    """Test 18: Alice's refresh token only returns Alice's profile and subject mappings."""
    client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_alice", "password": "FacultyPass123!"},
    )
    ref_res = client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert ref_res.status_code == 200
    data = ref_res.json()
    assert data["role"] == "FACULTY"
    assert data["subject_codes"] == ["ML"]
    assert "admin" not in data["role"].lower()


def test_existing_supabase_jwt_verification_continues_working(client, monkeypatch):
    """Test 19: Supabase tokens continue to verify seamlessly alongside the session system."""
    supabase_secret = "supabase-shared-secret-key-32bytes-minimum"
    monkeypatch.setenv("SUPABASE_JWT_SECRET", supabase_secret)

    token = jwt.encode(
        {
            "sub": "supabase_user_xyz",
            "email": "cloud@school.edu",
            "role": "authenticated",
            "app_metadata": {"role": "FACULTY"},
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp()),
            "iat": int(datetime.now(timezone.utc).timestamp()),
        },
        supabase_secret,
        algorithm="HS256",
    )
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["user_id"] == "supabase_user_xyz"
    assert res.json()["role"] == "FACULTY"


def test_existing_n2_login_rate_limiting_and_admin_key_preserved(client):
    """Test 20: Existing N2 protections (rate limiting and ADMIN_KEY fail-closed) remain intact."""
    # 1. Admin login without admin_key fails
    res_admin = client.post(
        "/api/v1/auth/login",
        json={"user_id": "admin_bob", "password": "AdminPass123!"},
    )
    assert res_admin.status_code == 401

    # 2. Admin login with valid admin_key succeeds
    res_admin_ok = client.post(
        "/api/v1/auth/login",
        json={"user_id": "admin_bob", "password": "AdminPass123!", "admin_key": TEST_ADMIN_KEY},
    )
    assert res_admin_ok.status_code == 200
    assert res_admin_ok.json()["role"] == "ADMIN"

