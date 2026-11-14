"""N16: demo seed must store verifiable bcrypt hashes, never plaintext."""

from __future__ import annotations

import bcrypt

from scripts.seed_demo import _demo_password, _hash_password


def test_hash_password_is_bcrypt_and_verifiable():
    plain = "admin_key_2026"
    hashed = _hash_password(plain)
    assert hashed != plain
    assert hashed.startswith("$2")
    assert bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def test_each_hash_uses_a_fresh_salt():
    first = _hash_password("same-password")
    second = _hash_password("same-password")
    assert first != second
    assert bcrypt.checkpw(b"same-password", first.encode("utf-8"))
    assert bcrypt.checkpw(b"same-password", second.encode("utf-8"))


def test_demo_password_can_be_overridden_per_user(monkeypatch):
    monkeypatch.setenv("SEED_PASSWORD_FACULTY_DS", "per-user-secret")
    assert _demo_password("faculty_ds", "fallback") == "per-user-secret"
    assert _demo_password("admin_root", "fallback") == "fallback"
