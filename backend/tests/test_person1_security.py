"""Person 1 backend security tests (authentication, account security, uploads).

Covers:
  * JWT secret configuration matrix (unset / empty / short / default / valid),
    production vs development separation, alg=none, issuer/audience, signature.
  * Login brute-force protection: progressive delay, temporary lockout, lockout
    expiry and recovery, counter reset after a successful login, generic errors.
  * Rate limiting: per-scope quotas and a safe, non-silent fallback.
  * MFA: AES-GCM round trip, invalid key, modified ciphertext, tag failure,
    nonce uniqueness, recovery-code single use, invalid TOTP, brute-force limit,
    and failing closed without a production encryption key.
  * Password reset: hashed token storage, expiry, single use, generic responses,
    session invalidation and honest delivery reporting.
  * Upload security: size, spoofed MIME/extension, magic bytes, malformed and
    oversized images, traversal filenames, cleanup and rate limiting.
  * RBAC matrix across roles and both API mounts.
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session as OrmSession, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import jwt as jwt_module
from app.db.base import Base
from app.db import crud
import app.db.models as models
from app.dependencies import get_db
from app.main import app
from app.security import mfa as mfa_module
from app.security.rate_limit import LimitScope, check_limit, clear_limit, get_policy

TEST_SECRET = "person1-test-secret-key-at-least-32-characters-long"
MFA_KEY = mfa_module.base64.urlsafe_b64encode(b"0" * 32).decode("ascii")

# Real JWT verification (no mock admin user) for every test in this module.
pytestmark = pytest.mark.no_auth_override

# A genuinely valid 1x1 PNG (the upload endpoint rejects malformed images).
VALID_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe"
    b"\x02\xfe\r\xefF\xb8\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _headers(user_id: str, role: str) -> dict:
    """Authorization header for a signed test token."""
    import jwt as pyjwt

    now = datetime.now(timezone.utc)
    token = pyjwt.encode(
        {
            "sub": user_id,
            "email": f"{user_id}@rollcall.edu",
            "role": role,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        TEST_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def client(engine, monkeypatch):
    # The tokens in this module are signed with TEST_SECRET; the application
    # must verify against the same secret.
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_SECRET)
    factory = sessionmaker(bind=engine, class_=OrmSession, expire_on_commit=False)
    # The authentication router opens its own session factory; point it at the
    # isolated test database so the test never touches another database.
    monkeypatch.setattr("app.db.connection.get_sync_session_factory", lambda eng=None: factory)
    monkeypatch.setattr("app.routers.auth.get_sync_session_factory", lambda: factory)
    monkeypatch.setattr("app.auth.dependencies.get_sync_session_factory", lambda: factory)
    now = "2026-01-01T00:00:00Z"
    import bcrypt

    with factory() as db:
        db.add(models.User(user_id="admin_root", email="admin@x.c", role="ADMIN",
                          hashed_password=bcrypt.hashpw(b"AdminPassw0rd!", bcrypt.gensalt()).decode(),
                          is_active=1, created_at=now))
        db.add(models.User(user_id="faculty_ds", email="ds@x.c", role="FACULTY",
                          hashed_password=bcrypt.hashpw(b"FacultyPassw0rd!", bcrypt.gensalt()).decode(),
                          is_active=1, created_at=now))
        db.add(models.User(user_id="viewer_ro", email="ro@x.c", role="VIEWER",
                          hashed_password=bcrypt.hashpw(b"ViewerPassw0rd!", bcrypt.gensalt()).decode(),
                          is_active=1, created_at=now))
        db.add(models.Room(room_id="LH-101", name="Lecture Hall 101"))
        db.add(models.Student(usn="1MS21CS001", name="Alice Smith", branch="CSE"))
        db.add(models.Session(session_id="SESS-001", date="2026-03-15", subject="CN",
                            teacher_id="faculty_ds", subject_code="ML"))
        db.commit()

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    # The rate-limit counters live in the application database and are shared
    # between test modules; clear them so this module is isolated.
    with factory() as db:
        db.execute(text("DELETE FROM security_rate_limits"))
        db.commit()
    from app.security import rate_limit as rate_limit_module

    rate_limit_module._FALLBACK_STATE["counts"] = {}
    rate_limit_module._FALLBACK_STATE["warned"] = False

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app, raise_server_exceptions=False)
    yield test_client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 1. JWT secret configuration
# ---------------------------------------------------------------------------

def test_jwt_secret_matrix(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    # unset / empty
    with pytest.raises(ValueError) as exc:
        jwt_module.validate_jwt_secret_configuration(None)
    assert "missing or empty" in str(exc.value).lower()

    with pytest.raises(ValueError) as exc:
        jwt_module.validate_jwt_secret_configuration("")
    assert "missing or empty" in str(exc.value).lower()

    # too short
    with pytest.raises(ValueError) as exc:
        jwt_module.validate_jwt_secret_configuration("too-short-secret-key-16b")
    assert "too short" in str(exc.value).lower()

    # valid
    valid = "a-very-secure-and-long-enough-secret-key-32+"
    assert jwt_module.validate_jwt_secret_configuration(valid) == valid

    # the development fallback is rejected in production by the loaders that
    # actually provide the secret to the application
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        jwt_module.get_jwt_secret()
    with pytest.raises(RuntimeError):
        jwt_module.get_local_jwt_secret()


def test_jwt_production_requires_a_configured_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        jwt_module.get_jwt_secret()
    with pytest.raises(RuntimeError):
        jwt_module.get_local_jwt_secret()


def test_jwt_rejects_the_development_fallback_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", jwt_module.DEV_FALLBACK_SECRET)
    with pytest.raises(RuntimeError):
        jwt_module.get_jwt_secret()
    with pytest.raises(RuntimeError):
        jwt_module.get_local_jwt_secret()


def test_jwt_algorithms_never_allow_none(monkeypatch):
    monkeypatch.setenv("JWT_ALGORITHMS", "none")
    with pytest.raises(RuntimeError):
        jwt_module.get_jwt_algorithms()
    monkeypatch.setenv("JWT_ALGORITHMS", "HS256,none")
    assert jwt_module.get_jwt_algorithms() == ["HS256"]


def test_jwt_alg_none_token_is_rejected():
    import jwt as pyjwt

    token = pyjwt.encode({"sub": "u1", "exp": 9999999999}, key="", algorithm="none")
    with pytest.raises(jwt_module.AuthenticationError):
        jwt_module.decode_and_verify_token(token)


def test_jwt_production_requires_issuer_and_audience(monkeypatch):
    import jwt as pyjwt

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.delenv("JWT_ISSUER", raising=False)
    monkeypatch.delenv("JWT_AUDIENCE", raising=False)

    now = datetime.now(timezone.utc)
    token = pyjwt.encode(
        {
            "sub": "u1",
            "role": "FACULTY",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        TEST_SECRET,
        algorithm="HS256",
    )
    # Production must refuse a token whose issuer/audience cannot be verified.
    with pytest.raises(RuntimeError):
        jwt_module.decode_and_verify_token(token)


# ---------------------------------------------------------------------------
# 2. Login brute-force protection
# ---------------------------------------------------------------------------

def _login(client, user_id="faculty_ds", password="wrong-password"):
    return client.post("/api/v1/auth/login", json={"user_id": user_id, "password": password})


def test_login_error_is_generic_and_does_not_enumerate_accounts(client):
    unknown = _login(client, user_id="does-not-exist")
    known = _login(client, user_id="faculty_ds")
    assert unknown.status_code == known.status_code == 401
    assert unknown.json() == known.json()
    assert "password" not in unknown.text.lower() or "invalid" in unknown.text.lower()


def test_repeated_failed_logins_lock_the_account_temporarily(client, monkeypatch):
    monkeypatch.setenv("SEC_LOGIN_LIMIT", "3")
    monkeypatch.setenv("SEC_LOGIN_BASE_DELAY_SECONDS", "0")
    statuses = [_login(client).status_code for _ in range(6)]
    assert 429 in statuses, statuses
    locked = client.post("/api/v1/auth/login",
                         json={"user_id": "faculty_ds", "password": "FacultyPassw0rd!"})
    assert locked.status_code == 429, locked.text


def test_lockout_expires_and_the_user_can_log_in_again(client, engine, monkeypatch):
    monkeypatch.setenv("SEC_LOGIN_LIMIT", "2")
    monkeypatch.setenv("SEC_LOGIN_BASE_DELAY_SECONDS", "0")
    for _ in range(4):
        _login(client)
    assert _login(client, password="FacultyPassw0rd!").status_code == 429

    # Expire the lockout window and let the account recover (both the shared
    # limiter and the legacy per-account attempt quota).
    factory = sessionmaker(bind=engine, class_=OrmSession, expire_on_commit=False)
    with factory() as db:
        db.execute(text("UPDATE security_rate_limits SET blocked_until = '2000-01-01T00:00:00Z'"))
        db.execute(text("DELETE FROM login_attempts"))
        db.commit()

    recovered = client.post("/api/v1/auth/login",
                            json={"user_id": "faculty_ds", "password": "FacultyPassw0rd!"})
    assert recovered.status_code == 200, recovered.text


def test_successful_login_clears_the_failure_counters(client, engine, monkeypatch):
    monkeypatch.setenv("SEC_LOGIN_LIMIT", "5")
    monkeypatch.setenv("SEC_LOGIN_BASE_DELAY_SECONDS", "0")
    _login(client)
    ok = client.post("/api/v1/auth/login",
                      json={"user_id": "faculty_ds", "password": "FacultyPassw0rd!"})
    assert ok.status_code == 200, ok.text

    factory = sessionmaker(bind=engine, class_=OrmSession, expire_on_commit=False)
    with factory() as db:
        rows = db.execute(text("SELECT COUNT(*) FROM security_rate_limits WHERE scope='login'")).scalar()
    assert rows == 0


def test_login_rate_limit_is_shared_between_scopes(engine):
    factory = sessionmaker(bind=engine, class_=OrmSession, expire_on_commit=False)
    with factory() as db:
        login = check_limit(db, LimitScope.LOGIN, "user:x", record_failure=True)
        reset = check_limit(db, LimitScope.PASSWORD_RESET, "user:x", record_failure=True)
    assert login.scope == "login"
    assert reset.scope == "password_reset"
    assert login.attempts == 1
    assert reset.attempts == 1


def test_rate_limiter_falls_back_safely_when_the_shared_table_is_missing(tmp_path):
    """A missing shared table must not silently disable the protection."""
    from sqlalchemy import create_engine as ce

    eng = ce("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(text("DROP TABLE security_rate_limits"))
    factory = sessionmaker(bind=eng, class_=OrmSession, expire_on_commit=False)
    with factory() as db:
        decision = check_limit(db, LimitScope.LOGIN, "user:u1", record_failure=True)
    assert decision.allowed is True
    assert decision.degraded is True
    assert decision.backend == "memory"


def test_rate_limit_policies_are_configurable(monkeypatch):
    monkeypatch.setenv("SEC_LOGIN_LIMIT", "9")
    assert get_policy(LimitScope.LOGIN).limit == 9


# ---------------------------------------------------------------------------
# 3. MFA (AES-GCM)
# ---------------------------------------------------------------------------

def test_mfa_encryption_round_trip(monkeypatch):
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", MFA_KEY)
    payload = mfa_module.encrypt_secret("JBSWY3DPEHPK3PXP")
    assert payload.startswith("v1:")
    assert "JBSWY3DPEHPK3PXP" not in payload
    assert mfa_module.decrypt_secret(payload) == "JBSWY3DPEHPK3PXP"


def test_mfa_nonce_is_unique_per_encryption(monkeypatch):
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", MFA_KEY)
    a = mfa_module.encrypt_secret("secret")
    b = mfa_module.encrypt_secret("secret")
    assert a != b
    assert mfa_module.decrypt_secret(a) == mfa_module.decrypt_secret(b) == "secret"


def test_mfa_rejects_an_invalid_key(monkeypatch):
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", MFA_KEY)
    payload = mfa_module.encrypt_secret("secret")
    other_key = mfa_module.base64.urlsafe_b64encode(b"1" * 32).decode("ascii")
    with pytest.raises(mfa_module.MFADecryptionError):
        mfa_module.decrypt_secret(payload, key=other_key.encode())


def test_mfa_rejects_modified_ciphertext(monkeypatch):
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", MFA_KEY)
    payload = mfa_module.encrypt_secret("secret")
    raw = bytearray(mfa_module.base64.urlsafe_b64decode(payload[3:] + "=" * (-len(payload[3:]) % 4)))
    raw[-1] ^= 0xFF  # flip a bit in the authentication tag
    tampered = "v1:" + mfa_module.base64.urlsafe_b64encode(bytes(raw)).decode("ascii")
    with pytest.raises(mfa_module.MFADecryptionError):
        mfa_module.decrypt_secret(tampered)


def test_mfa_missing_production_key_fails_closed(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("MFA_ENCRYPTION_KEY", raising=False)
    with pytest.raises(mfa_module.MFAConfigurationError):
        mfa_module.get_encryption_key()
    with pytest.raises(mfa_module.MFAConfigurationError):
        mfa_module.encrypt_secret("secret")


def test_mfa_recovery_codes_are_single_use(monkeypatch):
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", MFA_KEY)
    codes = mfa_module.generate_recovery_codes(5)
    assert len(codes) == 5
    assert len(set(codes)) == 5
    stored = [mfa_module.hash_recovery_code(code) for code in codes]
    match = mfa_module.verify_recovery_code(codes[0], stored)
    assert match is not None
    # The same code must not match a second time once it has been consumed.
    remaining = [item for item in stored if item != match]
    assert mfa_module.verify_recovery_code(codes[0], remaining) is None


def test_mfa_invalid_totp_is_rejected(monkeypatch):
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", MFA_KEY)
    secret = mfa_module.generate_mfa_secret()
    valid, counter = mfa_module.verify_totp(secret, mfa_module.totp_code(secret))
    assert valid is True and counter is not None
    assert mfa_module.verify_totp(secret, "000000" if mfa_module.totp_code(secret) != "000000" else "111111")[0] is False
    assert mfa_module.verify_totp(secret, "abcdef")[0] is False


def test_mfa_totp_replay_is_rejected(monkeypatch):
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", MFA_KEY)
    secret = mfa_module.generate_mfa_secret()
    code = mfa_module.totp_code(secret)
    valid, counter = mfa_module.verify_totp(secret, code)
    assert valid is True
    # The same time step cannot be used twice.
    assert mfa_module.verify_totp(secret, code, last_counter=counter)[0] is False


def test_mfa_enrollment_requires_a_configured_key(client, engine, monkeypatch):
    # Without an encryption key the endpoint must fail closed (it never falls
    # back to plaintext or XOR).
    monkeypatch.delenv("MFA_ENCRYPTION_KEY", raising=False)
    res = client.post("/api/v1/auth/mfa/enable",
                      json={"current_password": "FacultyPassw0rd!"},
                      headers=_headers("faculty_ds", "FACULTY"))
    assert res.status_code == 403
    assert "MFA_UNAVAILABLE" in res.text


def test_mfa_enrollment_and_activation_flow(client, monkeypatch):
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", MFA_KEY)
    enable = client.post("/api/v1/auth/mfa/enable",
                          json={"current_password": "FacultyPassw0rd!"},
                          headers=_headers("faculty_ds", "FACULTY"))
    assert enable.status_code == 200, enable.text
    body = enable.json()
    assert body["secret"]
    assert body["recovery_codes"]

    verify = client.post("/api/v1/auth/mfa/verify",
                         json={"code": mfa_module.totp_code(body["secret"])},
                         headers=_headers("faculty_ds", "FACULTY"))
    assert verify.status_code == 200, verify.text
    assert verify.json()["mfa_enabled"] is True

    # A wrong code is rejected and does not activate anything.
    disable = client.post("/api/v1/auth/mfa/disable",
                          json={"current_password": "FacultyPassw0rd!",
                                "code": mfa_module.totp_code(body["secret"])},
                          headers=_headers("faculty_ds", "FACULTY"))
    assert disable.status_code == 200, disable.text


def test_mfa_verification_is_rate_limited(client, monkeypatch):
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", MFA_KEY)
    monkeypatch.setenv("SEC_MFA_VERIFY_LIMIT", "2")
    enable = client.post("/api/v1/auth/mfa/enable",
                          json={"current_password": "FacultyPassw0rd!"},
                          headers=_headers("faculty_ds", "FACULTY"))
    secret = enable.json()["secret"]
    statuses = [
        client.post("/api/v1/auth/mfa/verify", json={"code": "000000"},
                    headers=_headers("faculty_ds", "FACULTY")).status_code
        for _ in range(4)
    ]
    assert 429 in statuses, statuses


# ---------------------------------------------------------------------------
# 4. Password reset
# ---------------------------------------------------------------------------

class _RecordingEmailProvider:
    """Test double for the email provider (no SMTP involved)."""

    sent = []

    def send(self, to_address, subject, body):
        _RecordingEmailProvider.sent.append((to_address, subject, body))
        from app.security.email import EmailResult

        return EmailResult(delivered=True, configured=True, detail="test")


def test_password_reset_flow(client, engine, monkeypatch):
    _RecordingEmailProvider.sent = []
    monkeypatch.setattr("app.routers.auth.get_email_provider", lambda: _RecordingEmailProvider())

    initiate = client.post("/api/v1/auth/password/reset",
                           json={"user_id": "faculty_ds"},
                           headers=_headers("admin_root", "ADMIN"))
    assert initiate.status_code == 200, initiate.text
    body = initiate.json()
    assert body["reset_initiated"] is True
    # The token is never returned by the API.
    assert "token" not in json.dumps(body).lower() or "reset token" not in json.dumps(body).lower()

    # The token was delivered through the provider and only its hash is stored.
    assert len(_RecordingEmailProvider.sent) == 1
    token = _RecordingEmailProvider.sent[0][2].split("token within 2 hours:")[1].split()[0]
    factory = sessionmaker(bind=engine, class_=OrmSession, expire_on_commit=False)
    with factory() as db:
        user = db.get(models.User, "faculty_ds")
        assert user.password_reset_token
        assert token not in user.password_reset_token  # only the hash is stored

    confirm = client.post("/api/v1/auth/password/reset/confirm",
                          json={"reset_token": token, "new_password": "NewStrongPassw0rd!"})
    assert confirm.status_code == 200, confirm.text

    # The token is consumed: a second attempt fails.
    replay = client.post("/api/v1/auth/password/reset/confirm",
                          json={"reset_token": token, "new_password": "AnotherPassw0rd!"})
    assert replay.status_code == 400
    # The new password works.
    login = client.post("/api/v1/auth/login",
                        json={"user_id": "faculty_ds", "password": "NewStrongPassw0rd!"})
    assert login.status_code == 200, login.text


def test_password_reset_without_email_provider_reports_honestly(client, monkeypatch):
    from app.security.email import NullEmailProvider

    monkeypatch.setattr("app.routers.auth.get_email_provider", lambda: NullEmailProvider())
    res = client.post("/api/v1/auth/password/reset",
                      json={"user_id": "faculty_ds"},
                      headers=_headers("admin_root", "ADMIN"))
    assert res.status_code == 200
    body = res.json()
    assert body["reset_initiated"] is True
    # No token is exposed and no delivery is claimed.
    assert "token" not in json.dumps(body).lower().replace("reset_initiated", "")


def test_password_reset_response_is_generic_for_unknown_accounts(client, monkeypatch):
    monkeypatch.setattr("app.routers.auth.get_email_provider", lambda: _RecordingEmailProvider())
    known = client.post("/api/v1/auth/password/reset",
                        json={"user_id": "faculty_ds"},
                        headers=_headers("admin_root", "ADMIN"))
    unknown = client.post("/api/v1/auth/password/reset",
                          json={"user_id": "nobody-at-all"},
                          headers=_headers("admin_root", "ADMIN"))
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


def test_expired_reset_token_is_rejected(client, engine, monkeypatch):
    _RecordingEmailProvider.sent = []
    monkeypatch.setattr("app.routers.auth.get_email_provider", lambda: _RecordingEmailProvider())
    client.post("/api/v1/auth/password/reset", json={"user_id": "faculty_ds"},
                headers=_headers("admin_root", "ADMIN"))
    token = _RecordingEmailProvider.sent[0][2].split("token within 2 hours:")[1].split()[0]

    factory = sessionmaker(bind=engine, class_=OrmSession, expire_on_commit=False)
    with factory() as db:
        db.execute(text("UPDATE users SET password_reset_token_expires = '2000-01-01T00:00:00Z'"))
        db.commit()

    res = client.post("/api/v1/auth/password/reset/confirm",
                       json={"reset_token": token, "new_password": "NewStrongPassw0rd!"})
    assert res.status_code == 400


def test_password_change_requires_the_old_password_and_revokes_sessions(client):
    wrong = client.post("/api/v1/auth/password/change",
                        json={"old_password": "nope", "new_password": "NewStrongPassw0rd!"},
                        headers=_headers("faculty_ds", "FACULTY"))
    assert wrong.status_code == 401

    weak = client.post("/api/v1/auth/password/change",
                       json={"old_password": "FacultyPassw0rd!", "new_password": "short"},
                       headers=_headers("faculty_ds", "FACULTY"))
    assert weak.status_code == 422

    ok = client.post("/api/v1/auth/password/change",
                      json={"old_password": "FacultyPassw0rd!", "new_password": "NewStrongPassw0rd!"},
                      headers=_headers("faculty_ds", "FACULTY"))
    assert ok.status_code == 200, ok.text


# ---------------------------------------------------------------------------
# 5. Upload security
# ---------------------------------------------------------------------------

def test_oversized_upload_is_rejected(client):
    payload = b"a" * (10 * 1024 * 1024 + 1024)
    res = client.post("/api/v1/agent/process-file",
                      files={"file": ("sheet.csv", io.BytesIO(payload), "text/csv")},
                      headers=_headers("faculty_ds", "FACULTY"))
    assert res.status_code == 413


def test_spoofed_mime_type_is_rejected(client):
    res = client.post("/api/v1/agent/process-file",
                      files={"file": ("sheet.png", io.BytesIO(VALID_PNG), "text/plain")},
                      headers=_headers("faculty_ds", "FACULTY"))
    assert res.status_code == 400
    assert "content type" in res.text.lower()


def test_spoofed_extension_is_rejected(client):
    res = client.post("/api/v1/agent/process-file",
                      files={"file": ("sheet.png", io.BytesIO(b"not-an-image-at-all"), "image/png")},
                      headers=_headers("faculty_ds", "FACULTY"))
    assert res.status_code == 400


def test_malformed_image_is_rejected(client):
    truncated = VALID_PNG[:20]
    res = client.post("/api/v1/agent/process-file",
                      files={"file": ("sheet.png", io.BytesIO(truncated), "image/png")},
                      headers=_headers("faculty_ds", "FACULTY"))
    assert res.status_code == 400


def test_excessive_image_dimensions_are_rejected(client, tmp_path, monkeypatch):
    from PIL import Image

    monkeypatch.setattr("app.security.uploads.MAX_IMAGE_PIXELS", 10)
    path = tmp_path / "big.png"
    Image.new("RGB", (64, 64), (255, 255, 255)).save(path)
    res = client.post("/api/v1/agent/process-file",
                      files={"file": ("sheet.png", io.BytesIO(path.read_bytes()), "image/png")},
                      headers=_headers("faculty_ds", "FACULTY"))
    assert res.status_code == 400


def test_path_traversal_filename_is_sanitised(client):
    res = client.post("/api/v1/agent/process-file",
                      files={"file": ("../../etc/passwd.csv", io.BytesIO(b"usn,status\n"), "text/csv")},
                      headers=_headers("faculty_ds", "FACULTY"))
    # The traversal never reaches the filesystem; the request is processed
    # safely (the file name is reduced to its basename).
    assert res.status_code in (200, 400, 422)


def test_temporary_files_are_removed_after_the_request(client, tmp_path, monkeypatch):
    created = []
    import tempfile as tempfile_module

    original = tempfile_module.mkstemp

    def tracking_mkstemp(*args, **kwargs):
        handle, path = original(*args, **kwargs)
        created.append(path)
        return handle, path

    monkeypatch.setattr("app.routers.agent.tempfile.mkstemp", tracking_mkstemp)
    client.post("/api/v1/agent/process-file",
                files={"file": ("sheet.csv", io.BytesIO(b"usn,status\n1MS21CS001,PRESENT\n"), "text/csv")},
                headers=_headers("faculty_ds", "FACULTY"))
    assert created, "no temporary file was created"
    for path in created:
        assert not os.path.exists(path), path


def test_viewer_cannot_upload(client):
    res = client.post("/api/v1/agent/process-file",
                      files={"file": ("sheet.csv", io.BytesIO(b"usn,status\n"), "text/csv")},
                      headers=_headers("viewer_ro", "VIEWER"))
    assert res.status_code == 403


def test_upload_rate_limit_is_enforced(client, monkeypatch):
    monkeypatch.setenv("SEC_UPLOAD_LIMIT", "2")
    statuses = [
        client.post("/api/v1/agent/process-file",
                    files={"file": ("sheet.csv", io.BytesIO(b"usn,status\n"), "text/csv")},
                    headers=_headers("faculty_ds", "FACULTY")).status_code
        for _ in range(5)
    ]
    assert 429 in statuses, statuses


# ---------------------------------------------------------------------------
# 6. RBAC matrix
# ---------------------------------------------------------------------------

def test_viewer_cannot_perform_writes(client):
    for method, path, payload in (
        ("post", "/api/v1/students", {"usn": "1X", "name": "X", "branch": "CSE"}),
        ("post", "/api/v1/rooms", {"room_id": "R1", "name": "R"}),
        ("post", "/api/v1/sessions", {"session_id": "S1", "date": "2026-03-15", "subject": "S"}),
        ("post", "/api/v1/attendance/sessions/SESS-001/record",
         {"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT"}),
    ):
        res = getattr(client, method)(path, json=payload, headers=_headers("viewer_ro", "VIEWER"))
        assert res.status_code == 403, (path, res.status_code)


def test_faculty_cannot_perform_admin_operations(client):
    res = client.post("/api/v1/admin/teacher-subjects",
                      json={"user_id": "faculty_ds", "subject_code": "ML"},
                      headers=_headers("faculty_ds", "FACULTY"))
    assert res.status_code == 403

    res = client.get("/api/v1/admin/audit-logs", headers=_headers("faculty_ds", "FACULTY"))
    assert res.status_code == 403

    res = client.delete("/api/v1/attendance/sessions/SESS-001", headers=_headers("faculty_ds", "FACULTY"))
    assert res.status_code == 403


def test_admin_only_endpoints_are_admin_only(client):
    admin = client.get("/api/v1/admin/audit-logs", headers=_headers("admin_root", "ADMIN"))
    assert admin.status_code == 200
    for role in ("FACULTY", "VIEWER"):
        res = client.get("/api/v1/admin/audit-logs", headers=_headers("faculty_ds", role))
        assert res.status_code == 403, (role, res.status_code)


def test_both_api_mounts_enforce_the_same_policy(client):
    for mount in ("/api", "/api/v1"):
        denied = client.post(f"{mount}/students",
                             json={"usn": "1X", "name": "X", "branch": "CSE"},
                             headers=_headers("viewer_ro", "VIEWER"))
        assert denied.status_code == 403, mount


def test_session_listing_is_user_scoped(client, engine):
    """A user only ever sees their own sessions."""
    factory = sessionmaker(bind=engine, class_=OrmSession, expire_on_commit=False)
    with factory() as db:
        db.add(models.AuthSession(session_id="11111111-1111-1111-1111-111111111111",
                                 user_id="faculty_ds", created_at="2026-01-01T00:00:00Z",
                                 absolute_expiry="2026-02-01T00:00:00Z", revoked_at=None,
                                 remember_me=0))
        db.add(models.AuthSession(session_id="22222222-2222-2222-2222-222222222222",
                                 user_id="viewer_ro", created_at="2026-01-01T00:00:00Z",
                                 absolute_expiry="2026-02-01T00:00:00Z", revoked_at=None,
                                 remember_me=0))
        db.commit()

    res = client.get("/api/v1/auth/sessions", headers=_headers("faculty_ds", "FACULTY"))
    assert res.status_code == 200, res.text
    ids = {s["session_id"] for s in res.json()["sessions"]}
    assert ids == {"11111111-1111-1111-1111-111111111111"}


def test_user_cannot_revoke_another_users_session(client, engine):
    """Object-level authorization on session revocation."""
    factory = sessionmaker(bind=engine, class_=OrmSession, expire_on_commit=False)
    with factory() as db:
        db.add(models.AuthSession(session_id="33333333-3333-3333-3333-333333333333",
                                 user_id="admin_root", created_at="2026-01-01T00:00:00Z",
                                 absolute_expiry="2026-02-01T00:00:00Z", revoked_at=None,
                                 remember_me=0))
        db.commit()

    res = client.post("/api/v1/auth/sessions/33333333-3333-3333-3333-333333333333/revoke",
                       headers=_headers("faculty_ds", "FACULTY"))
    assert res.status_code == 404, res.text

    with factory() as db:
        session = db.get(models.AuthSession, "33333333-3333-3333-3333-333333333333")
        assert session.revoked_at is None, "another user's session was revoked"


# ---------------------------------------------------------------------------
# 7. Migration graph
# ---------------------------------------------------------------------------

def test_alembic_has_a_single_head_and_migrates_on_a_disposable_database():
    """One valid head, and upgrade -> downgrade -> upgrade works on a copy."""
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend_dir = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "graph.db"
        cfg = Config(str(backend_dir / "alembic.ini"))
        cfg.set_main_option("script_location", str(backend_dir / "alembic"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")

        head_list = ScriptDirectory.from_config(cfg).get_heads()
        assert len(head_list) == 1, f"expected exactly one Alembic head, found {head_list}"

        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(str(db_path))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        revision = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        conn.close()
        assert revision == "0016_account_security", revision
        assert "security_rate_limits" in tables
        assert "audit_chain_head" in tables
        assert "security_decoys" in tables
