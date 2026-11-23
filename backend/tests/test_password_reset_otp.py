"""Tests for the OTP-based password reset flow (/password/forgot, /password/verify-otp)."""

import os
import tempfile
from datetime import datetime, timezone

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session as SqlSession

from app.auth.otp import otp_codes
from app.db.base import Base
from app.db.models import User
from app.main import app


@pytest.fixture
def otp_client(monkeypatch):
    """Fresh SQLite database with a seeded user and the otp_codes table."""
    temp_dir = tempfile.mkdtemp()
    engine = create_engine(f"sqlite:///{os.path.join(temp_dir, 'otp_test.db')}")
    Base.metadata.create_all(engine)
    otp_codes.create(bind=engine, checkfirst=True)

    SessionLocal = sessionmaker(bind=engine, class_=SqlSession, expire_on_commit=False)
    monkeypatch.setattr("app.db.connection.get_sync_session_factory", lambda eng=None: SessionLocal)
    monkeypatch.setattr("app.routers.auth.get_sync_session_factory", lambda: SessionLocal)
    monkeypatch.setenv("APP_ENV", "testing")

    with SessionLocal() as db:
        db.add(
            User(
                user_id="teacher_jane",
                email="jane@school.edu",
                role="FACULTY",
                hashed_password=bcrypt.hashpw(
                    b"FacultyPass123!", bcrypt.gensalt()
                ).decode("utf-8"),
                is_active=1,
                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        )
        db.commit()

    return TestClient(app)


def _forgot(client, identifier):
    return client.post("/api/v1/auth/password/forgot", json={"user_identifier": identifier})


def _verify(client, identifier, code, new_password=None):
    payload = {"user_identifier": identifier, "otp_code": code}
    if new_password is not None:
        payload["new_password"] = new_password
    return client.post("/api/v1/auth/password/verify-otp", json=payload)


def test_forgot_password_returns_generic_response_and_dev_otp(otp_client):
    res = _forgot(otp_client, "teacher_jane")

    assert res.status_code == 200
    body = res.json()
    assert "6-digit OTP" in body["message"]
    assert body["otp_expires_in_seconds"] == 600
    # APP_ENV=testing is not production, so the code is echoed for the caller.
    assert len(body.get("otp", "")) == 6


def test_forgot_password_unknown_account_is_indistinguishable(otp_client):
    res = _forgot(otp_client, "does_not_exist_at_all")

    assert res.status_code == 200
    body = res.json()
    assert "6-digit OTP" in body["message"]
    assert "otp" not in body


def test_forgot_password_accepts_email_case_insensitively(otp_client):
    res = _forgot(otp_client, "JANE@SCHOOL.EDU")

    assert res.status_code == 200
    assert len(res.json().get("otp", "")) == 6


def test_verify_rejects_wrong_code(otp_client):
    otp = _forgot(otp_client, "teacher_jane").json()["otp"]

    wrong = "000000" if otp != "000000" else "111111"
    res = _verify(otp_client, "teacher_jane", wrong, "BrandNewPass123!")

    assert res.status_code == 400
    assert res.json()["detail"]["error"]["code"] == "INVALID_OTP"


def test_verify_with_new_password_resets_login_credentials(otp_client):
    otp = _forgot(otp_client, "teacher_jane").json()["otp"]

    res = _verify(otp_client, "teacher_jane", otp, "BrandNewPass123!")

    assert res.status_code == 200
    assert res.json()["password_reset"] is True

    # Old password no longer works, the new one does.
    old_login = otp_client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_jane", "password": "FacultyPass123!"},
    )
    assert old_login.status_code == 401

    new_login = otp_client.post(
        "/api/v1/auth/login",
        json={"user_id": "teacher_jane", "password": "BrandNewPass123!"},
    )
    assert new_login.status_code == 200


def test_verify_consumes_the_code(otp_client):
    otp = _forgot(otp_client, "teacher_jane").json()["otp"]

    assert _verify(otp_client, "teacher_jane", otp).status_code == 200
    # A used code can never be replayed.
    assert _verify(otp_client, "teacher_jane", otp).status_code == 400


def test_verify_without_new_password_returns_single_use_reset_token(otp_client):
    otp = _forgot(otp_client, "teacher_jane").json()["otp"]

    res = _verify(otp_client, "teacher_jane", otp)

    assert res.status_code == 200
    reset_token = res.json()["reset_token"]
    assert len(reset_token) > 20

    confirm = otp_client.post(
        "/api/v1/auth/password/reset/confirm",
        json={"reset_token": reset_token, "new_password": "AnotherPass123!"},
    )
    assert confirm.status_code == 200
    assert confirm.json()["password_reset"] is True


def test_lookup_account_returns_masked_email_for_existing_user(otp_client):
    res = otp_client.post(
        "/api/v1/auth/password/lookup-account",
        json={"user_identifier": "teacher_jane"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["found"] is True
    assert data["user_id"] == "teacher_jane"
    assert "@school.edu" in data["email_masked"]


def test_lookup_account_handles_nonexistent_user_gracefully(otp_client):
    res = otp_client.post(
        "/api/v1/auth/password/lookup-account",
        json={"user_identifier": "ghost_user_123"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["found"] is False
