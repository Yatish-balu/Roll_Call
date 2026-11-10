"""FastAPI dependency injection utilities."""

from __future__ import annotations

import logging
from typing import Generator
from sqlalchemy.orm import Session
from app.db.connection import get_sync_session_factory

logger = logging.getLogger("rollcall.dependencies")

# Singleton default sessionmaker instance (lazy initialized)
_sync_session_factory = None


def get_session_factory():
    """Get or initialize the synchronous sessionmaker."""
    global _sync_session_factory
    if _sync_session_factory is None:
        _sync_session_factory = get_sync_session_factory()
    return _sync_session_factory


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency yielding a synchronous SQLAlchemy Session.
    Ensures:
    - Proper commit or rollback on exception.
    - Guaranteed session close.
    - Zero separate database connection systems (uses app.db.connection).
    """
    factory = get_session_factory()
    session: Session = factory()
    try:
        yield session
    except Exception as exc:
        logger.error("Exception during database transaction: %s", exc)
        session.rollback()
        raise
    finally:
        session.close()

