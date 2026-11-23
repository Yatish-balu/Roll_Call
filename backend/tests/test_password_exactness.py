"""P0 regression: authentication must accept only the exact stored password.

The audit found transformed password variants being accepted. Login now hashes
and compares the submitted password verbatim; these tests lock that behaviour
in for a Faculty account with punctuation in its credential.
"""

import os
import tempfile
from datetime import datetime, timezone

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SqlSession, sessionmaker

from app.db.base import Base
from app.db.models import User
from app.main import app

EXACT_PASSWORD = "Fac!ultyPass_2026"


@pytest.fixture
def client(monkeypatch):
    temp_dir = tempfile.mkdtemp()
    engine = create_engine(f"sqlite:///{os.path.join(temp_dir, 'exact_pw.db')}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, class_=SqlSession, expire_on_commit=False)
    monkeypatch.setattr("app.db.connection.get_sync_session_factory", lambda eng=None: SessionLocal)
    monkeypatch.setattr("app.routers.auth.get_sync_session_factory", lambda: SessionLocal)
    monkeypatch.setenv("APP_ENV", "testing")

    with SessionLocal() as db:
        db.add(
            User(
                user_id="faculty_cn",
                email="faculty.cn@rollcall.internal",
                role="FACULTY",
                hashed_password=bcrypt.hashpw(
                    EXACT_PASSWORD.encode("utf-8"), bcrypt.gensalt()
                ).decode("utf-8"),
                is_active=1,
                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        )
        db.commit()

    return TestClient(app)


def _login(client, password):
    return client.post(
        "/api/v1/auth/login",
        json={"user_id": "faculty_cn", "password": password},
    )


def test_exact_password_succeeds(client):
    assert _login(client, EXACT_PASSWORD).status_code == 200


@pytest.mark.parametrize(
    "variant",
    [
        f" {EXACT_PASSWORD}",
        f"{EXACT_PASSWORD} ",
        EXACT_PASSWORD.replace("!", ""),
        EXACT_PASSWORD.replace("!", " "),
        EXACT_PASSWORD.lower(),
    ],
)
def test_password_variants_are_rejected(client, variant):
    response = _login(client, variant)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
