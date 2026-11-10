"""Tests for Phase 5.1: FastAPI backend core infrastructure."""

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.dependencies import get_db
from app.db.base import Base
from app.db.models import Student


@pytest.fixture
def client():
    """FastAPI TestClient configured not to raise server exceptions directly so status_code is returned."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def test_engine():
    """In-memory SQLite engine with StaticPool so all connections share the same in-memory DB."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


# ==============================================================================
# 1. Health & Root Endpoint Tests
# ==============================================================================

def test_read_root_endpoint(client):
    """Verify that GET / returns the expected welcome message."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to RollCall AI API"}


def test_health_check_endpoint(client):
    """Verify that GET /health returns status healthy and environment."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "environment" in data
    assert "version" in data


# ==============================================================================
# 2. CORS Middleware Tests
# ==============================================================================

def test_cors_headers_allowed_origin(client):
    """Verify CORS preflight and headers for allowed origin."""
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


# ==============================================================================
# 3. Database Dependency Session Lifecycle Tests
# ==============================================================================

def test_get_db_session_lifecycle(test_engine):
    """Verify that get_db yields an active session and closes it cleanly."""
    TestingSessionLocal = sessionmaker(bind=test_engine, class_=Session, expire_on_commit=False)

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    # Register temporary test endpoint
    @app.get("/test/db-session")
    def db_session_test_endpoint(db: Session = Depends(get_db)):
        assert db.is_active
        students = db.scalars(select(Student)).all()
        return {"students_count": len(students)}

    test_client = TestClient(app, raise_server_exceptions=False)
    response = test_client.get("/test/db-session")
    assert response.status_code == 200
    assert response.json() == {"students_count": 0}

    # Clean up override
    app.dependency_overrides.clear()


def test_get_db_rollback_on_exception(test_engine):
    """Verify that get_db rolls back the transaction when an exception occurs."""
    TestingSessionLocal = sessionmaker(bind=test_engine, class_=Session, expire_on_commit=False)

    # Use generator directly to verify rollback on exception throw
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.dependencies.get_session_factory", lambda: TestingSessionLocal)
        gen = get_db()
        sess = next(gen)
        sess.add(Student(usn="1MS21CS999", name="Rollback Test", branch="CSE"))
        with pytest.raises(RuntimeError):
            try:
                raise RuntimeError("Simulated failure")
            except Exception as exc:
                gen.throw(exc)

    # Verify student was rolled back and not committed
    verify_session = TestingSessionLocal()
    assert verify_session.query(Student).filter_by(usn="1MS21CS999").first() is None
    verify_session.close()


# ==============================================================================
# 4. Exception Handling Tests
# ==============================================================================

def test_value_error_exception_handler(client):
    """Verify that ValueError is converted to 400 Bad Request without leaking tracebacks."""
    @app.get("/test/value-error")
    def raise_value_error():
        raise ValueError("Invalid attendance status supplied")

    response = client.get("/test/value-error")
    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "BadRequest"
    assert data["message"] == "Invalid attendance status supplied"
    assert "traceback" not in data


def test_unhandled_exception_handler(client):
    """Verify that unhandled exceptions return 500 without leaking sensitive error messages."""
    @app.get("/test/internal-error")
    def raise_internal_error():
        raise RuntimeError("Internal database secret password connection leak")

    response = client.get("/test/internal-error")
    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "InternalServerError"
    assert "Internal database secret" not in data["message"]
