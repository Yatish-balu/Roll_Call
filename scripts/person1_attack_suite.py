"""Person 1 adversarial security harness (authentication + backend hardening).

Runs real HTTP probes against the FastAPI application on a disposable database.
Every probe prints SECURE / VULNERABLE / BROKEN / INFO so the result can be
pasted into a report. Nothing here modifies the live development database.

Usage:
    cd Roll_Call
    python scripts/person1_attack_suite.py
"""

from __future__ import annotations

import base64
import os
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

TMP_DIR = tempfile.mkdtemp(prefix="rc_attack_")
DB_PATH = Path(TMP_DIR) / "attack.db"

TEST_SECRET = "attack-suite-secret-key-0123456789-abcdefgh"
ADMIN_KEY = "attack-admin-key-123456"
MFA_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")

# Must be set before any app module is imported.
os.environ.update(
    {
        "SQLITE_PATH": str(DB_PATH),
        "DATABASE_PATH": str(DB_PATH),
        "DB_BACKEND": "sqlite",
        "APP_ENV": "development",
        "JWT_SECRET": TEST_SECRET,
        "ADMIN_KEY": ADMIN_KEY,
        "MFA_ENCRYPTION_KEY": MFA_KEY,
        "ALLOWED_ORIGINS": "http://localhost:5173",
        "REDIS_URL": "",
        "SMTP_HOST": "",
    }
)

import bcrypt  # noqa: E402
import jwt as pyjwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, delete  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: E402
from app.db.connection import get_sync_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.auth import AuthenticatedUser, Role  # noqa: E402
from app.security.mfa import encrypt_secret, generate_mfa_secret  # noqa: E402
from app.auth.session_scope import resolve_data_scope  # noqa: E402
from tools.query_tool import safe_sql_query  # noqa: E402

PW = "Str0ng!Passw0rd"
RESULTS: list[tuple[str, str, str, str, str]] = []


def rec(pid: str, name: str, severity: str, verdict: str, detail: str = "") -> None:
    RESULTS.append((pid, name, severity, verdict, detail))
    print(f"[{verdict:10s}] {pid:5s} {name} :: {detail}", flush=True)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hash_pw(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


# ---------------------------------------------------------------------------
# Disposable database + seed
# ---------------------------------------------------------------------------

engine = create_engine(f"sqlite:///{DB_PATH}", future=True)
Base.metadata.create_all(engine)
SF = sessionmaker(bind=engine, expire_on_commit=False)

MFA_SECRET_PLAIN = generate_mfa_secret()

with SF() as db:
    db.add_all(
        [
            models.User(user_id="admin1", email="admin@x.edu", role="ADMIN",
                        hashed_password=hash_pw(PW), is_active=1, created_at=utcnow()),
            models.User(user_id="fac_a", email="a@x.edu", role="FACULTY",
                        hashed_password=hash_pw(PW), is_active=1, created_at=utcnow()),
            models.User(user_id="fac_b", email="b@x.edu", role="FACULTY",
                        hashed_password=hash_pw(PW), is_active=1, created_at=utcnow()),
            models.User(user_id="viewer1", email="v@x.edu", role="VIEWER",
                        hashed_password=hash_pw(PW), is_active=1, created_at=utcnow()),
            models.User(user_id="mfa_user", email="m@x.edu", role="FACULTY",
                        hashed_password=hash_pw(PW), is_active=1, created_at=utcnow(),
                        mfa_secret=encrypt_secret(MFA_SECRET_PLAIN), mfa_enabled=1),
            models.Room(room_id="LH-101", name="Lecture Hall 101"),
            models.Room(room_id="LH-102", name="Lecture Hall 102"),
            models.Student(usn="1MS21CS001", name="Alice Alpha", branch="CSE"),
            models.Student(usn="1MS21CS002", name="Bob Beta", branch="CSE"),
            models.Session(session_id="SESS-A", date="2026-03-15", subject="Networks",
                           teacher_id="fac_a", subject_code="CS101", created_at=utcnow()),
            models.Session(session_id="SESS-B", date="2026-03-16", subject="Databases",
                           teacher_id="fac_b", subject_code="CS102", created_at=utcnow()),
        ]
    )
    db.commit()
    db.add_all(
        [
            models.Attendance(attendance_id=str(uuid.uuid4()), session_id="SESS-A",
                              usn="1MS21CS001", room_id="LH-101", status="PRESENT",
                              source="manual", confidence=1.0, recorded_at=utcnow()),
            models.Attendance(attendance_id=str(uuid.uuid4()), session_id="SESS-B",
                              usn="1MS21CS002", room_id="LH-102", status="ABSENT",
                              source="manual", confidence=1.0, recorded_at=utcnow()),
        ]
    )
    db.commit()


def mk(ip: str) -> TestClient:
    """TestClient bound to a distinct source address (isolates IP quotas)."""
    try:
        return TestClient(app, client=(ip, 50000), raise_server_exceptions=False)
    except TypeError:  # older Starlette
        return TestClient(app, raise_server_exceptions=False)


def H(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def login(client: TestClient, uid: str, pw: str = PW, admin_key: str | None = None,
          headers: dict | None = None):
    body = {"user_id": uid, "password": pw}
    if admin_key is not None:
        body["admin_key"] = admin_key
    return client.post("/api/v1/auth/login", json=body, headers=headers or {})


def tok(client: TestClient, uid: str, admin_key: str | None = None) -> str:
    r = login(client, uid, admin_key=admin_key)
    return r.json().get("token", "")


CSRF = {"X-Requested-With": "XMLHttpRequest"}

print("=" * 100)
print("PERSON 1 ADVERSARIAL SECURITY HARNESS")
print(f"database: {DB_PATH}")
print("=" * 100)

# ===========================================================================
# P1 - JWT / token forgery
# ===========================================================================
c1 = mk("198.51.100.10")
admin_tok = tok(c1, "admin1", admin_key=ADMIN_KEY)
fac_a_tok = tok(c1, "fac_a")
fac_b_tok = tok(c1, "fac_b")
viewer_tok = tok(c1, "viewer1")
mfa_tok = tok(c1, "mfa_user")

# P1.1 algorithm confusion: unsigned token
try:
    none_tok = pyjwt.encode(
        {"sub": "admin1", "role": "ADMIN", "exp": int(time.time()) + 600},
        key=None, algorithm="none",
    )
    r = c1.get("/api/v1/students", headers=H(none_tok))
    rec("P1.1", "alg=none forged token", "critical",
        "SECURE" if r.status_code == 401 else "VULNERABLE", f"HTTP {r.status_code}")
except Exception as exc:
    rec("P1.1", "alg=none forged token", "critical", "ERROR", str(exc))

# P1.2 token signed with the committed development fallback secret
try:
    from app.auth.jwt import DEV_FALLBACK_SECRET
    dev_tok = pyjwt.encode(
        {"sub": "admin1", "role": "ADMIN", "exp": int(time.time()) + 600},
        DEV_FALLBACK_SECRET, algorithm="HS256",
    )
    r = c1.get("/api/v1/students", headers=H(dev_tok))
    rec("P1.2", "token signed with dev fallback secret", "critical",
        "SECURE" if r.status_code == 401 else "VULNERABLE", f"HTTP {r.status_code}")
except Exception as exc:
    rec("P1.2", "token signed with dev fallback secret", "critical", "ERROR", str(exc))

# P1.3 privilege escalation through user_metadata
try:
    esc = pyjwt.encode(
        {"sub": "viewer1", "role": "VIEWER", "exp": int(time.time()) + 600,
         "user_metadata": {"role": "ADMIN"}, "app_metadata": {"role": "VIEWER"}},
        TEST_SECRET, algorithm="HS256",
    )
    r = c1.post("/api/v1/students", headers=H(esc),
                json={"usn": "1MS21CS099", "name": "Hacker", "branch": "CSE"})
    rec("P1.3", "user_metadata role escalation", "critical",
        "SECURE" if r.status_code == 403 else "VULNERABLE", f"HTTP {r.status_code}")
except Exception as exc:
    rec("P1.3", "user_metadata role escalation", "critical", "ERROR", str(exc))

# P1.4 expired token
try:
    old = pyjwt.encode(
        {"sub": "admin1", "role": "ADMIN",
         "exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200},
        TEST_SECRET, algorithm="HS256",
    )
    r = c1.get("/api/v1/students", headers=H(old))
    rec("P1.4", "expired token replay", "high",
        "SECURE" if r.status_code == 401 else "VULNERABLE", f"HTTP {r.status_code}")
except Exception as exc:
    rec("P1.4", "expired token replay", "high", "ERROR", str(exc))

# P1.5 deleted account keeps working (token of a removed user)
try:
    with SF() as db:
        db.add(models.User(user_id="ghost", email="ghost@x.edu", role="FACULTY",
                           hashed_password=hash_pw(PW), is_active=1, created_at=utcnow()))
        db.commit()
    ghost_tok = tok(mk("198.51.100.11"), "ghost")
    with SF() as db:
        db.execute(delete(models.User).where(models.User.user_id == "ghost"))
        db.commit()
    r = c1.get("/api/v1/auth/me", headers=H(ghost_tok))
    rec("P1.5", "deleted user token still accepted", "medium",
        "VULNERABLE" if r.status_code == 200 else "SECURE", f"HTTP {r.status_code}")
except Exception as exc:
    rec("P1.5", "deleted user token still accepted", "medium", "ERROR", str(exc))

# ===========================================================================
# P2 - MFA
# ===========================================================================
try:
    r = login(mk("198.51.100.12"), "mfa_user")
    bypassed = r.status_code == 200
    rec("P2.1", "MFA-enrolled account logs in with password only", "critical",
        "VULNERABLE" if bypassed else "SECURE",
        f"HTTP {r.status_code} (no TOTP code supplied; mfa_enabled=1)")
except Exception as exc:
    rec("P2.1", "MFA-enrolled account logs in with password only", "critical", "ERROR", str(exc))

try:
    r = c1.get("/api/v1/auth/me", headers=H(mfa_tok))
    leaked = "mfa_secret" in r.text or "recovery" in r.text
    rec("P2.2", "MFA secret / recovery codes exposed by profile API", "high",
        "VULNERABLE" if leaked else "SECURE", f"HTTP {r.status_code}")
except Exception as exc:
    rec("P2.2", "MFA secret / recovery codes exposed by profile API", "high", "ERROR", str(exc))

try:
    cc = mk("198.51.100.13")
    codes = [cc.post("/api/v1/auth/mfa/enable",
                     json={"current_password": f"Wrong{i}!Passw0rd"}, headers=H(fac_a_tok)).status_code
             for i in range(15)]
    rec("P2.3", "unlimited password guessing on /auth/mfa/enable", "high",
        "VULNERABLE" if 429 not in codes else "SECURE",
        f"statuses={sorted(set(codes))} after 15 wrong passwords")
except Exception as exc:
    rec("P2.3", "unlimited password guessing on /auth/mfa/enable", "high", "ERROR", str(exc))

try:
    cd = mk("198.51.100.14")
    codes = [cd.post("/api/v1/auth/password/change",
                     json={"old_password": f"Wrong{i}!Passw0rd",
                           "new_password": "An0ther!Passw0rd"}, headers=H(fac_b_tok)).status_code
             for i in range(15)]
    rec("P2.4", "unlimited password guessing on /auth/password/change", "high",
        "VULNERABLE" if 429 not in codes else "SECURE",
        f"statuses={sorted(set(codes))} after 15 wrong passwords")
except Exception as exc:
    rec("P2.4", "unlimited password guessing on /auth/password/change", "high", "ERROR", str(exc))

# ===========================================================================
# P3 - Rate limiting, lockout, DoS
# ===========================================================================
try:
    cl = mk("198.51.100.20")
    statuses = [login(cl, "victim1", "Wrong!Passw0rd1").status_code for _ in range(6)]
    rec("P3.1", "per-account lockout after repeated failures", "medium",
        "SECURE" if 429 in statuses else "VULNERABLE", f"statuses={statuses}")
except Exception as exc:
    rec("P3.1", "per-account lockout after repeated failures", "medium", "ERROR", str(exc))

try:
    cl2 = mk("198.51.100.21")
    for _ in range(5):
        login(cl2, "victim2", "Wrong!Passw0rd1")
    r = login(cl2, "victim2", PW)  # correct password
    rec("P3.2", "lockout also blocks the legitimate correct password", "high",
        "VULNERABLE" if r.status_code == 429 else "SECURE",
        f"HTTP {r.status_code} with valid credentials (account-lockout DoS)")
except Exception as exc:
    rec("P3.2", "lockout also blocks the legitimate correct password", "high", "ERROR", str(exc))

try:
    cl3 = mk("198.51.100.22")
    lat = []
    for _ in range(5):
        t0 = time.perf_counter()
        login(cl3, "victim3", "Wrong!Passw0rd1")
        lat.append(round(time.perf_counter() - t0, 2))
    growth = lat[-1] - lat[0]
    rec("P3.3", "failed logins hold the global login lock while sleeping", "high",
        "VULNERABLE" if growth >= 0.4 else "SECURE",
        f"per-attempt seconds={lat} (progressive delay is applied inside a process-wide lock)")
except Exception as exc:
    rec("P3.3", "failed logins hold the global login lock while sleeping", "high", "ERROR", str(exc))

try:
    cip = mk("203.0.113.77")
    statuses = [login(cip, f"nobody{i}", "Wrong!Passw0rd1").status_code for i in range(22)]
    r = login(cip, "fac_a", PW)
    rec("P3.4", "shared-IP failure quota locks out every user behind that IP", "high",
        "VULNERABLE" if r.status_code == 429 else "SECURE",
        f"unknown-user attempts={statuses.count(429)}x429; valid login afterwards HTTP {r.status_code}")
except Exception as exc:
    rec("P3.4", "shared-IP failure quota locks out every user behind that IP", "high", "ERROR", str(exc))

try:
    cu = mk("198.51.100.23")
    t_unknown = []
    t_known = []
    for i in range(4):
        t0 = time.perf_counter()
        login(cu, f"ghost_user_{i}", "Wrong!Passw0rd1")
        t_unknown.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        login(cu, "fac_b", "Wrong!Passw0rd1")
        t_known.append(time.perf_counter() - t0)
    au = sum(t_unknown) / len(t_unknown)
    ak = sum(t_known) / len(t_known)
    rec("P3.5", "username enumeration through login timing", "medium",
        "VULNERABLE" if (ak - au) > 0.05 else "SECURE",
        f"mean known-user={ak:.3f}s unknown-user={au:.3f}s delta={ak - au:.3f}s")
except Exception as exc:
    rec("P3.5", "username enumeration through login timing", "medium", "ERROR", str(exc))

# ===========================================================================
# P4 - Sessions, refresh rotation, CSRF
# ===========================================================================
try:
    cr = mk("198.51.100.30")
    login(cr, "fac_a")
    r = cr.post("/api/v1/auth/refresh")
    rec("P4.1", "refresh without CSRF header", "high",
        "SECURE" if r.status_code == 403 else "VULNERABLE", f"HTTP {r.status_code}")
    r = cr.post("/api/v1/auth/refresh", headers={**CSRF, "Origin": "https://evil.example"})
    rec("P4.2", "refresh from untrusted Origin", "high",
        "SECURE" if r.status_code == 403 else "VULNERABLE", f"HTTP {r.status_code}")
except Exception as exc:
    rec("P4.1", "refresh CSRF checks", "high", "ERROR", str(exc))

try:
    crot = mk("198.51.100.31")
    login(crot, "fac_a")
    old = crot.cookies.get("rollcall_refresh_token")
    r1 = crot.post("/api/v1/auth/refresh", headers=CSRF)
    new = crot.cookies.get("rollcall_refresh_token")
    rotated = r1.status_code == 200 and old and new and old != new
    rec("P4.3", "refresh token rotation", "high",
        "SECURE" if rotated else "VULNERABLE", f"HTTP {r1.status_code}, rotated={bool(rotated)}")
    reuse = TestClient(app, raise_server_exceptions=False)
    r2 = reuse.post("/api/v1/auth/refresh", headers={**CSRF, "Cookie": f"rollcall_refresh_token={old}"})
    rec("P4.4", "replayed refresh token detected and family revoked", "high",
        "SECURE" if r2.status_code == 401 else "VULNERABLE",
        f"HTTP {r2.status_code} {r2.json().get('detail', '')}")
    r3 = reuse.post("/api/v1/auth/refresh",
                    headers={**CSRF, "Cookie": f"rollcall_refresh_token={new}"})
    rec("P4.5", "new token invalid after reuse detection", "high",
        "SECURE" if r3.status_code == 401 else "VULNERABLE", f"HTTP {r3.status_code}")
except Exception as exc:
    rec("P4.3", "refresh rotation / reuse detection", "high", "ERROR", str(exc))

try:
    ca = mk("198.51.100.32")
    login(ca, "admin1", admin_key=ADMIN_KEY)
    admin_sessions = ca.get("/api/v1/auth/sessions", headers=H(admin_tok)).json().get("sessions", [])
    admin_sid = next((s["session_id"] for s in admin_sessions), None)
    cb = mk("198.51.100.33")
    login(cb, "fac_b")
    r = cb.post(f"/api/v1/auth/sessions/revoke/{admin_sid}", headers=H(fac_b_tok))
    rec("P4.6", "cross-user session revocation (IDOR)", "high",
        "VULNERABLE" if r.status_code == 200 else "SECURE",
        f"faculty revoked another account's session -> HTTP {r.status_code}")
except Exception as exc:
    rec("P4.6", "cross-user session revocation (IDOR)", "high", "ERROR", str(exc))

try:
    r = c1.post("/api/v1/auth/sessions/revoke-all", headers=H(fac_b_tok))
    rec("P4.7", "/auth/sessions/revoke-all works", "medium",
        "BROKEN" if r.status_code >= 500 else "SECURE", f"HTTP {r.status_code}")
except Exception as exc:
    rec("P4.7", "/auth/sessions/revoke-all works", "medium", "BROKEN", str(exc)[:120])

try:
    r = c1.post("/api/v1/auth/logout", headers=CSRF)
    rec("P4.8", "logout is callable without authentication", "low",
        "INFO", f"HTTP {r.status_code} (unauthenticated logout accepted)")
except Exception as exc:
    rec("P4.8", "logout is callable without authentication", "low", "ERROR", str(exc))

# ===========================================================================
# P5 - API authorization / attendance tampering
# ===========================================================================
try:
    r = c1.post("/api/v1/attendance/sessions/SESS-A/record", headers=H(fac_b_tok),
                json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "ABSENT",
                      "source": "manual"}, params={"upsert": "true"})
    rec("P5.1", "cross-faculty attendance write", "critical",
        "VULNERABLE" if r.status_code in (200, 201) else "SECURE", f"HTTP {r.status_code}")
    r = c1.get("/api/v1/attendance/sessions/SESS-A", headers=H(fac_b_tok))
    rec("P5.2", "cross-faculty attendance read", "high",
        "VULNERABLE" if r.status_code == 200 else "SECURE", f"HTTP {r.status_code}")
    r = c1.get("/api/v1/sessions/SESS-A", headers=H(fac_b_tok))
    rec("P5.3", "cross-faculty session metadata read", "high",
        "VULNERABLE" if r.status_code == 200 else "SECURE", f"HTTP {r.status_code}")
    r = c1.get("/api/v1/analytics/sessions/SESS-A/summary", headers=H(fac_b_tok))
    rec("P5.4", "cross-faculty analytics read", "high",
        "VULNERABLE" if r.status_code == 200 else "SECURE", f"HTTP {r.status_code}")
    r = c1.get("/api/v1/attendance/students/1MS21CS001", headers=H(fac_b_tok))
    body = r.json() if r.status_code == 200 else []
    leaked = isinstance(body, list) and len(body) > 0
    rec("P5.5", "cross-faculty student attendance history", "high",
        "VULNERABLE" if leaked else "SECURE",
        f"HTTP {r.status_code}, rows={len(body) if isinstance(body, list) else 'n/a'}")
except Exception as exc:
    rec("P5.1", "attendance scope enforcement", "critical", "ERROR", str(exc))

try:
    r1 = c1.post("/api/v1/attendance/sessions/SESS-A/record", headers=H(viewer_tok),
                 json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT",
                       "source": "manual"})
    r2 = c1.delete("/api/v1/attendance/sessions/SESS-A", headers=H(viewer_tok))
    r3 = c1.post("/api/v1/students", headers=H(viewer_tok),
                 json={"usn": "1MS21CS098", "name": "V", "branch": "CSE"})
    r4 = c1.post("/api/v1/agent/process-file", headers=H(viewer_tok),
                 files={"file": ("s.csv", b"usn,status\n1MS21CS001,PRESENT\n", "text/csv")})
    ok = all(r.status_code == 403 for r in (r1, r2, r3, r4))
    rec("P5.6", "VIEWER cannot perform writes", "critical",
        "SECURE" if ok else "VULNERABLE",
        f"record={r1.status_code} delete={r2.status_code} student={r3.status_code} upload={r4.status_code}")
except Exception as exc:
    rec("P5.6", "VIEWER cannot perform writes", "critical", "ERROR", str(exc))

try:
    r = c1.post("/api/v1/attendance/sessions/SESS-A/record", headers=H(fac_a_tok),
                json={"session_id": "SESS-B", "usn": "1MS21CS001", "room_id": "LH-101",
                      "status": "PRESENT", "source": "manual"})
    rec("P5.7", "session-id tampering (body vs path)", "high",
        "SECURE" if r.status_code == 400 else "VULNERABLE", f"HTTP {r.status_code}")
except Exception as exc:
    rec("P5.7", "session-id tampering (body vs path)", "high", "ERROR", str(exc))

try:
    r = c1.post("/api/v1/attendance/sessions/SESS-A/record", headers=H(fac_a_tok),
                json={"usn": "  1ms21cs001  ", "room_id": "LH-101", "status": "PRESENT",
                      "source": "manual"}, params={"upsert": "true"})
    normalized = r.status_code in (200, 201) and r.json().get("usn") == "1MS21CS001"
    rec("P5.8", "USN normalization/case tampering", "medium",
        "SECURE" if normalized else "VULNERABLE",
        f"HTTP {r.status_code} usn={r.json().get('usn') if r.status_code < 300 else 'n/a'}")
except Exception as exc:
    rec("P5.8", "USN normalization/case tampering", "medium", "ERROR", str(exc))

try:
    ra = c1.get("/api/v1/admin/audit-logs", headers=H(admin_tok))
    rf = c1.get("/api/v1/admin/audit-logs", headers=H(fac_a_tok))
    rec("P5.9", "admin-only audit endpoint", "high",
        "SECURE" if ra.status_code == 200 and rf.status_code == 403 else "VULNERABLE",
        f"admin={ra.status_code} faculty={rf.status_code}")
    r = c1.get("/api/v1/admin/teacher-subjects", headers=H(fac_a_tok))
    rec("P5.10", "admin-only teacher-subject endpoint", "medium",
        "SECURE" if r.status_code == 403 else "VULNERABLE", f"HTTP {r.status_code}")
except Exception as exc:
    rec("P5.9", "admin-only endpoints", "high", "ERROR", str(exc))

# ===========================================================================
# P6 - Upload hardening
# ===========================================================================
def upload(client: TestClient, token: str, name: str, data: bytes, ctype: str):
    return client.post("/api/v1/agent/process-file", headers=H(token),
                       files={"file": (name, data, ctype)})


try:
    cu = mk("198.51.100.40")
    r = upload(cu, fac_a_tok, "big.csv", b"a" * (10 * 1024 * 1024 + 2048), "text/csv")
    rec("P6.1", "upload larger than 10 MB rejected", "high",
        "SECURE" if r.status_code == 413 else "VULNERABLE", f"HTTP {r.status_code}")
    r = upload(cu, fac_a_tok, "sheet.csv", b"MZ\x90\x00" + b"payload", "text/csv")
    rec("P6.2", "executable signature disguised as CSV", "high",
        "SECURE" if r.status_code == 400 else "VULNERABLE", f"HTTP {r.status_code}")
    r = upload(cu, fac_a_tok, "photo.png", b"\xff\xd8\xff\xe0" + b"jpeg", "image/png")
    rec("P6.3", "extension/content mismatch (JPEG bytes named .png)", "medium",
        "SECURE" if r.status_code == 400 else "VULNERABLE", f"HTTP {r.status_code}")
    r = upload(cu, fac_a_tok, "evil.exe", b"MZ\x90\x00", "application/octet-stream")
    rec("P6.4", "dangerous extension rejected", "medium",
        "SECURE" if r.status_code == 400 else "VULNERABLE", f"HTTP {r.status_code}")
    r = upload(cu, fac_a_tok, "empty.csv", b"", "text/csv")
    rec("P6.5", "empty upload rejected", "low",
        "SECURE" if r.status_code == 400 else "VULNERABLE", f"HTTP {r.status_code}")
    r = upload(cu, fac_a_tok, "../../../escape.csv",
               b"usn,status\n1MS21CS001,PRESENT\n", "text/csv")
    escaped = (REPO / "escape.csv").exists() or (Path.cwd() / "escape.csv").exists()
    rec("P6.6", "path traversal in upload filename", "high",
        "VULNERABLE" if escaped else "SECURE",
        f"HTTP {r.status_code}, file written outside temp={escaped}")
    r = upload(cu, fac_a_tok, "bomb.png",
               b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR"
               + (30000).to_bytes(4, "big") + (30000).to_bytes(4, "big")
               + b"\x08\x02\x00\x00\x00" + b"\x00" * 64, "image/png")
    rec("P6.7", "decompression-bomb image rejected", "medium",
        "SECURE" if r.status_code == 400 else "VULNERABLE", f"HTTP {r.status_code}")
    r = upload(cu, fac_a_tok, "polyglot.png",
               b"\x89PNG\r\n\x1a\n" + b"MZ\x90\x00" + b"malware", "image/png")
    rec("P6.8", "image polyglot with appended executable body", "low",
        "INFO", f"HTTP {r.status_code} (only the magic header is inspected)")
    r = upload(cu, fac_a_tok, "nul.csv",
               b"usn,status\n1MS21CS001,PRESENT\n\x00\x00TRUNC", "text/csv")
    rec("P6.9", "NUL bytes beyond the first 64 KB chunk", "low",
        "INFO", f"HTTP {r.status_code} (only first_chunk is NUL-scanned)")
except Exception as exc:
    rec("P6.1", "upload hardening", "high", "ERROR", str(exc))

# ===========================================================================
# P7 - AI query tool SQL scope bypass
# ===========================================================================
try:
    with SF() as db:
        scope = resolve_data_scope(db, AuthenticatedUser(user_id="fac_b", role=Role.FACULTY,
                                                        email="b@x.edu"))
        def sessions_in(sql: str) -> str:
            res = safe_sql_query(sql, db_target=db, scope=scope)
            out = sorted({str(r.get("session_id")) for r in res.data if r.get("session_id")})
            return ",".join(out) if out else "none"

        base = sessions_in("SELECT usn, session_id FROM attendance")
        quoted = sessions_in('SELECT usn, session_id FROM "attendance"')
        brack = sessions_in("SELECT usn, session_id FROM [attendance]")
        subq = sessions_in("SELECT usn, session_id FROM (SELECT usn, session_id FROM attendance)")
        rec("P7.1", "SQL scope filter baseline (unquoted table)", "high",
            "SECURE" if base == "SESS-B" else "INFO", f"visible sessions={base}")
        for pid, label, value in (
            ("P7.2", 'double-quoted table FROM "attendance"', quoted),
            ("P7.3", "bracket-quoted table FROM [attendance]", brack),
            ("P7.4", "derived table FROM (SELECT ... FROM attendance)", subq),
        ):
            leaked = "SESS-A" in value
            rec(pid, f"scope bypass via {label}", "high",
                "VULNERABLE" if leaked else "SECURE", f"visible sessions={value}")
except Exception as exc:
    rec("P7.2", "SQL scope rewriting bypass", "high", "ERROR", str(exc))

# ===========================================================================
# P8 - Password reset
# ===========================================================================
try:
    cp = mk("198.51.100.50")
    r = cp.post("/api/v1/auth/password/reset", headers=H(fac_a_tok),
                json={"user_id": "admin1"})
    rec("P8.1", "faculty can trigger a reset for an ADMIN account", "medium",
        "VULNERABLE" if r.status_code == 200 else "SECURE",
        f"HTTP {r.status_code} (no approval, no self-service reset for locked-out users)")
except Exception as exc:
    rec("P8.1", "faculty can trigger a reset for an ADMIN account", "medium", "ERROR", str(exc))

try:
    import hashlib
    token = "reset-token-attack-123"
    with SF() as db:
        u = db.get(models.User, "fac_b")
        u.password_reset_token = hashlib.sha256(token.encode()).hexdigest()
        u.password_reset_token_expires = (datetime.now(timezone.utc) + timedelta(hours=1)
                                          ).strftime("%Y-%m-%dT%H:%M:%SZ")
        db.commit()
    cpr = mk("198.51.100.51")
    r1 = cpr.post("/api/v1/auth/password/reset/confirm",
                  json={"reset_token": token, "new_password": "N3w!Passw0rd"})
    r2 = cpr.post("/api/v1/auth/password/reset/confirm",
                  json={"reset_token": token, "new_password": "N3w!Passw0rd2"})
    rec("P8.2", "reset token is single use", "high",
        "SECURE" if r1.status_code == 200 and r2.status_code == 400 else "VULNERABLE",
        f"first={r1.status_code} replay={r2.status_code}")
    with SF() as db:
        u = db.get(models.User, "fac_b")
        u.password_reset_token = hashlib.sha256(b"expired-token").hexdigest()
        u.password_reset_token_expires = "2020-01-01T00:00:00Z"
        db.commit()
    r3 = cpr.post("/api/v1/auth/password/reset/confirm",
                  json={"reset_token": "expired-token", "new_password": "N3w!Passw0rd"})
    rec("P8.3", "expired reset token rejected", "high",
        "SECURE" if r3.status_code == 400 else "VULNERABLE", f"HTTP {r3.status_code}")
    cpr.post("/api/v1/auth/password/reset/confirm",
             json={"reset_token": "expired-token", "new_password": "N3w!Passw0rd"})
except Exception as exc:
    rec("P8.2", "password reset token handling", "high", "ERROR", str(exc))

# ===========================================================================
# P9 - Information disclosure
# ===========================================================================
try:
    r = c1.get("/health")
    rec("P9.1", "/health discloses deployment environment", "low",
        "VULNERABLE" if "environment" in r.text else "SECURE",
        f"HTTP {r.status_code} body={r.text[:90]}")
    r = c1.get("/docs")
    rec("P9.2", "interactive API docs exposed", "low",
        "VULNERABLE" if r.status_code == 200 else "SECURE", f"HTTP {r.status_code}")
    r = c1.get("/openapi.json")
    rec("P9.3", "OpenAPI schema exposed unauthenticated", "low",
        "VULNERABLE" if r.status_code == 200 else "SECURE",
        f"HTTP {r.status_code}, {len(r.text)} bytes")
except Exception as exc:
    rec("P9.1", "information disclosure", "low", "ERROR", str(exc))

# ===========================================================================
# Summary
# ===========================================================================
print("=" * 100)
counts: dict[str, int] = {}
for _, _, _, verdict, _ in RESULTS:
    counts[verdict] = counts.get(verdict, 0) + 1
print("SUMMARY", counts)
print()
for pid, name, severity, verdict, detail in RESULTS:
    if verdict in ("VULNERABLE", "BROKEN", "ERROR"):
        print(f"  {verdict:10s} {pid:5s} [{severity}] {name} :: {detail}")
print("=" * 100)
