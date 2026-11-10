"""Tests for 24-hour edit lock policy (Prompt N5 / Playbook Table T-LOCK)."""

from datetime import datetime, timedelta, timezone
import pytest
from app.policy import is_editable, editable_until


def test_t_lock_table_all_rows():
    """Verify all 7 rows of T-LOCK from Section 9 of the Playbook."""
    base_created = datetime(2026, 11, 10, 10, 0, 0, tzinfo=timezone.utc)

    # Row 1: Teacher, Same day 10:00:00 (Age: 0 h) -> Editable
    now_0h = base_created
    assert is_editable(base_created, "teacher", now_0h) is True

    # Row 2: Teacher, Next day 09:59:59 (Age: 23 h 59 m 59 s) -> Editable
    now_23h59m = base_created + timedelta(hours=23, minutes=59, seconds=59)
    assert is_editable(base_created, "teacher", now_23h59m) is True

    # Row 3: Teacher, Next day 10:00:00 (Age: exactly 24 h) -> Editable
    now_24h = base_created + timedelta(hours=24)
    assert is_editable(base_created, "teacher", now_24h) is True

    # Row 4: Teacher, Next day 10:00:01 (Age: 24 h 0 m 1 s) -> Locked
    now_24h1s = base_created + timedelta(hours=24, seconds=1)
    assert is_editable(base_created, "teacher", now_24h1s) is False

    # Row 5: Teacher, 7 days later (Age: 7 days) -> Locked
    now_7d = base_created + timedelta(days=7)
    assert is_editable(base_created, "teacher", now_7d) is False

    # Row 6: Admin, 30 days later (Age: 30 days) -> Editable
    now_30d = base_created + timedelta(days=30)
    assert is_editable(base_created, "admin", now_30d) is True

    # Row 7: Teacher, Created time in the future (Negative age / clock error) -> Editable, no crash
    now_future = base_created - timedelta(hours=2)
    assert is_editable(base_created, "teacher", now_future) is True


def test_editable_until_calculation():
    """Verify editable_until returns created_at + 24 hours."""
    created = datetime(2026, 11, 10, 10, 0, 0, tzinfo=timezone.utc)
    until = editable_until(created)
    assert until == datetime(2026, 11, 11, 10, 0, 0, tzinfo=timezone.utc)


def test_string_iso_handling():
    """Verify string ISO timestamp parsing."""
    iso_created = "2026-11-10T10:00:00Z"
    now_under = datetime(2026, 11, 11, 9, 30, 0, tzinfo=timezone.utc)
    now_over = datetime(2026, 11, 11, 10, 30, 0, tzinfo=timezone.utc)

    assert is_editable(iso_created, "FACULTY", now_under) is True
    assert is_editable(iso_created, "FACULTY", now_over) is False
    assert is_editable(iso_created, "ADMIN", now_over) is True

