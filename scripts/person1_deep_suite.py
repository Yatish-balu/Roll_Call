"""Person 1 DEEP adversarial suite — new attack angles beyond the first audit.

Focus areas not covered by the earlier harness:
  * bcrypt 72-byte password truncation
  * JWT header/claim abuse (`kid`, `sub` type confusion)
  * SQL injection and encoding tricks on path parameters
  * cross-faculty write paths not previously probed (PUT / bulk / reconcile)
  * refresh-token theft, refresh after password change
  * concurrent lockout race
  * Excel/CSV formula injection through the report export
  * audit `actor_role` completeness, unversioned-router parity, MFA fail-closed

Usage:
    cd Roll_Call
    PYTHONPATH=backend python scripts/person1_deep_suite.py
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

TMP_DIR = tempfile.mkdtemp(prefix="rc_p1_deep_")
DB_PATH = Path(TMP_DIR) / "deep.db"

TEST_SECRET = "deep-suite-secret-key-0123456789-abcdefghij"
ADMIN_KEY = "deep-admin-key-123456"
MFA_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")

os.environ.update({
    "SQLITE_PATH": str(DB_PATH), "DATABASE_PATH": str(DB_PATH), "DB_BACKEND": "sqlite",
    "APP_ENV": "development", "JWT_SECRET": TEST_SECRET, "ADMIN_KEY": ADMIN_KEY,
    "MFA_ENCRYPTION_KEY": MFA_KEY, "ALLOWED_ORIGINS": "http://localhost:5173",
    "REDIS_URL": "", "SMTP_HOST": "",
})

import bcrypt  # noqa: E402
import jwt as pyjwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: E402
from app.main import app  # noqa: E402
from app.security.mfa import encrypt_secret, generate_mfa_secret  # noqa: E402

PW = "Str0ng!Passw0rd"
LONG_PW = "A" * 72
FORMULA_NAME = '=HYPERLINK("http://evil.example/x","click")'
RESULTS: list[tuple[str, str, str, str, str]] = []


def rec(pid: str, name: str, severity: str, verdict: str, detail: str = "") -> None:
    RESULTS.append((pid, name, severity, verdict, detail))
    print(f"[{verdict:10s}] {pid:5s} {name} :: {detail}", flush=True)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hash_pw(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


engine = create_engine(f"sqlite:///{DB_PATH}", future=True)
Base.metadata.create_all(engine)
SF = sessionmaker(bind=engine, expire_on_commit=False)

with SF() as db:
    db.add_all([
        models.User(user_id="admin1", email="admin@x.edu", role="ADMIN",
                    hashed_password=hash_pw(PW), is_active=1, created_at=utcnow()),
        models.User(user_id="fac_a", email="a@x.edu", role="FACULTY",
                    hashed_password=hash_pw(PW), is_active=1, created_at=utcnow()),
        models.User(user_id="fac_b", email="b@x.edu", role="FACULTY",
                    hashed_password=hash_pw(PW), is_active=1, created_at=utcnow()),
        models.User(user_id="viewer1", email="v@x.edu", role="VIEWER",
                    hashed_password=hash_pw(PW), is_active=1, created_at=utcnow()),
        models.User(user_id="trunc1", email="t@x.edu", role="FACULTY",
                    hashed_password=hash_pw(LONG_PW), is_active=1, created_at=utcnow()),
        models.User(user_id="pwuser", email="p@x.edu", role="FACULTY",
                    hashed_password=hash_pw(PW), is_active=1, created_at=utcnow()),
        models.User(user_id="mfa_user", email="m@x.edu", role="FACULTY",
                    hashed_password=hash_pw(PW), is_active=1, created_at=utcnow(),
                    mfa_secret=encrypt_secret(generate_mfa_secret()), mfa_enabled=1),
        models.Room(room_id="LH-101", name="Lecture Hall 101"),
        models.Student(usn="1MS21CS001", name="Alice Alpha", branch="CSE"),
        models.Student(usn="1MS21CS002", name="Bob Beta", branch="CSE"),
        models.Session(session_id="SESS-A", date="2026-03-15", subject="Networks",
                       teacher_id="fac_a", subject_code="CS101", created_at=utcnow()),
        models.Session(session_id="SESS-B", date="2026-03-16", subject="Databases",
                       teacher_id="fac_b", subject_code="CS102", created_at=utcnow()),
        models.Session(session_id="SESS-ADM", date="2026-03-17", subject="Admin Session",
                       teacher_id="admin1", subject_code="ADM101", created_at=utcnow()),
    ])
    db.commit()
    db.add_all([
        models.Attendance(attendance_id=str(uuid.uuid4()), session_id="SESS-A",
                          usn="1MS21CS001", room_id="LH-101", status="PRESENT",
                          source="manual", confidence=1.0, recorded_at=utcnow()),
        models.Attendance(attendance_id=str(uuid.uuid4()), session_id="SESS-B",
                          usn="1MS21CS002", room_id="LH-101", status="ABSENT",
                          source="manual", confidence=1.0, recorded_at=utcnow()),
    ])
    db.commit()


def mk(ip: str) -> TestClient:
    try:
        return TestClient(app, client=(ip, 50000), raise_server_exceptions=False)
    except TypeError:
        return TestClient(app, raise_server_exceptions=False)


def H(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def login(client, uid, pw=PW, admin_key=None):
    body = {"user_id": uid, "password": pw}
    if admin_key is not None:
        body["admin_key"] = admin_key
    return client.post("/api/v1/auth/login", json=body)


def tok(client, uid, admin_key=None) -> str:
    return login(client, uid, admin_key=admin_key).json().get("token", "")


CSRF = {"X-Requested-With": "XMLHttpRequest"}
print("=" * 100)
print("PERSON 1 DEEP ADVERSARIAL SUITE")
print("=" * 100)

c = mk("198.51.100.70")
admin_tok = tok(c, "admin1", admin_key=ADMIN_KEY)
fac_a_tok = tok(c, "fac_a")
fac_b_tok = tok(c, "fac_b")
viewer_tok = tok(c, "viewer1")

# ===========================================================================
# D1/D2 - bcrypt 72-byte truncation
# ===========================================================================
try:
    r = login(mk("198.51.100.71"), "trunc1", LONG_PW + "TOTALLY-DIFFERENT-TAIL")
    rec("D1", "bcrypt 72-byte password truncation", "high",
        "VULNERABLE" if r.status_code == 200 else "SECURE",
        f"HTTP {r.status_code} — a different 80-byte password authenticated via the shared 72-byte prefix"
        if r.status_code == 200 else f"HTTP {r.status_code}")
except Exception as exc:
    rec("D1", "bcrypt truncation", "high", "ERROR", str(exc))

try:
    long_new = "B" * 72 + "ignored-tail-1"
    r = c.post("/api/v1/auth/password/change", headers=H(fac_b_tok),
               json={"old_password": PW, "new_password": long_new})
    accepted = r.status_code == 200
    alt = login(mk("198.51.100.72"), "fac_b", "B" * 72 + "another-tail") if accepted else None
    rec("D2", "password policy accepts >72-byte passwords whose tail is ignored", "medium",
        "VULNERABLE" if accepted and alt is not None and alt.status_code == 200 else "SECURE",
        f"change={r.status_code}, login-with-different-tail={getattr(alt, 'status_code', 'n/a')}")
    if accepted:
        with SF() as db:
            u = db.get(models.User, "fac_b")
            u.hashed_password = hash_pw(PW)
            db.commit()
except Exception as exc:
    rec("D2", "long password policy", "medium", "ERROR", str(exc))

# ===========================================================================
# D3/D4 - JWT header and claim abuse
# ===========================================================================
try:
    now = int(time.time())
    kid_tok = pyjwt.encode(
        {"sub": "fac_a", "role": "FACULTY", "exp": now + 600, "iat": now},
        TEST_SECRET, algorithm="HS256", headers={"kid": "../../../../etc/passwd"},
    )
    r = c.get("/api/v1/me/subjects", headers=H(kid_tok))
    rec("D3", "`kid` path-traversal header is ignored (no key-file read)", "medium",
        "SECURE" if r.status_code == 200 else "INFO", f"HTTP {r.status_code}")
except Exception as exc:
    rec("D3", "kid header abuse", "medium", "ERROR", str(exc))

try:
    now = int(time.time())
    sub_list = pyjwt.encode(
        {"sub": ["admin1"], "role": "ADMIN", "exp": now + 600, "iat": now},
        TEST_SECRET, algorithm="HS256",
    )
    r = c.get("/api/v1/auth/me", headers=H(sub_list))
    rec("D4", "non-string `sub` claim accepted as an identity", "medium",
        "VULNERABLE" if r.status_code == 200 else "SECURE",
        f"HTTP {r.status_code} body={(r.text or '')[:90]}")
except Exception as exc:
    rec("D4", "sub type confusion", "medium", "ERROR", str(exc))

# ===========================================================================
# D5/D6 - injection / encoding in path parameters
# ===========================================================================
for pid, sid, label in (
    ("D5", "SESS-A' OR '1'='1", "SQL injection in session path"),
    ("D6", "sess-a", "case-variant session id"),
):
    try:
        r = c.get(f"/api/v1/attendance/sessions/{sid}", headers=H(fac_a_tok))
        rec(pid, label, "high" if pid == "D5" else "low",
            "SECURE" if r.status_code in (400, 403, 404) else "VULNERABLE", f"HTTP {r.status_code}")
    except Exception as exc:
        rec(pid, label, "high", "ERROR", str(exc))

try:
    r = c.get("/api/v1/attendance/students/1MS21CS001%27%20OR%20%271%27%3D%271", headers=H(fac_a_tok))
    rec("D7", "SQL injection in student USN path", "high",
        "SECURE" if r.status_code in (400, 403, 404) else "VULNERABLE", f"HTTP {r.status_code}")
except Exception as exc:
    rec("D7", "USN injection", "high", "ERROR", str(exc))

# ===========================================================================
# D8 - cross-faculty write paths not previously probed
# ===========================================================================
try:
    payload = {"records": [{"usn": "1MS21CS001", "room_id": "LH-101",
                            "status": "ABSENT", "source": "manual"}]}
    put = c.put("/api/v1/attendance/sessions/SESS-A", headers=H(fac_b_tok), json=payload)
    bulk = c.post("/api/v1/attendance/sessions/SESS-A/bulk", headers=H(fac_b_tok), json=payload)
    recon = c.post("/api/v1/attendance/sessions/SESS-A/reconcile", headers=H(fac_b_tok),
                   json={"resolutions": [{"usn": "1MS21CS001", "resolved_status": "ABSENT"}]})
    rec("D8", "cross-faculty replace / bulk / reconcile blocked", "critical",
        "SECURE" if all(r.status_code == 403 for r in (put, bulk, recon)) else "VULNERABLE",
        f"put={put.status_code} bulk={bulk.status_code} reconcile={recon.status_code}")
except Exception as exc:
    rec("D8", "cross-faculty write paths", "critical", "ERROR", str(exc))

# ===========================================================================
# D9/D10 - refresh token theft and post-password-change revocation
# ===========================================================================
try:
    ca = mk("198.51.100.73")
    login(ca, "fac_a")
    stolen = ca.cookies.get("rollcall_refresh_token")
    cb = mk("203.0.113.200")  # different client address
    r = cb.post("/api/v1/auth/refresh",
                headers={**CSRF, "Cookie": f"rollcall_refresh_token={stolen}"})
    rec("D9", "refresh token usable from a different client/IP (no binding)", "medium",
        "VULNERABLE" if r.status_code == 200 else "SECURE",
        f"HTTP {r.status_code} — stolen cookie replayed from a new IP")
except Exception as exc:
    rec("D9", "refresh token binding", "medium", "ERROR", str(exc))

try:
    cp = mk("198.51.100.74")
    login(cp, "pwuser")
    old_cookie = cp.cookies.get("rollcall_refresh_token")
    ch = cp.post("/api/v1/auth/password/change", headers=H(tok(cp, "pwuser")),
                 json={"old_password": PW, "new_password": "N3w!Passw0rd"})
    r = cp.post("/api/v1/auth/refresh", headers={**CSRF, "Cookie": f"rollcall_refresh_token={old_cookie}"})
    rec("D10", "password change revokes existing refresh tokens", "high",
        "SECURE" if ch.status_code == 200 and r.status_code == 401 else "VULNERABLE",
        f"change={ch.status_code} refresh_with_old_cookie={r.status_code}")
except Exception as exc:
    rec("D10", "post-password-change revocation", "high", "ERROR", str(exc))

# ===========================================================================
# D11 - concurrent lockout race
# ===========================================================================
try:
    def attempt(i: int) -> int:
        return login(mk(f"203.0.113.{60 + i}"), "raceuser", "Wrong!Passw0rd1").status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(attempt, range(8)))
    passed = statuses.count(401)
    rec("D11", "concurrent login attempts cannot exceed the failure quota", "high",
        "VULNERABLE" if passed > 5 else "SECURE",
        f"8 parallel attempts -> 401x{passed}, 429x{statuses.count(429)}")
except Exception as exc:
    rec("D11", "lockout race", "high", "ERROR", str(exc))

# ===========================================================================
# D12 - Excel formula injection through the report export
# ===========================================================================
try:
    r = c.post("/api/v1/students", headers=H(admin_tok),
               json={"usn": "1MS21CS777", "name": FORMULA_NAME, "branch": "CSE"})
    created = r.status_code in (200, 201)
    att = c.post("/api/v1/attendance/sessions/SESS-ADM/record", headers=H(admin_tok),
                 json={"usn": "1MS21CS777", "room_id": "LH-101", "status": "PRESENT",
                       "source": "manual"})
    exp = c.post("/api/v1/reports/export/excel", headers=H(admin_tok),
                 json={"session_id": "SESS-ADM"})
    formula_cells = 0
    if exp.status_code == 200 and exp.content:
        try:
            from openpyxl import load_workbook

            wb = load_workbook(io.BytesIO(exp.content))
            for ws in wb.worksheets:
                for row in ws.iter_rows():
                    for cell in row:
                        if cell.data_type == "f" or (
                            isinstance(cell.value, str) and cell.value.startswith("=")
                        ):
                            formula_cells += 1
        except Exception:
            pass
    rec("D12", "CSV/Excel formula injection through report export", "medium",
        "VULNERABLE" if formula_cells else "SECURE",
        f"student_created={created} attendance={att.status_code} export={exp.status_code} "
        f"formula_cells={formula_cells}")
except Exception as exc:
    rec("D12", "formula injection", "medium", "ERROR", str(exc))

# ===========================================================================
# D13 - audit completeness (actor_role on an attendance write)
# ===========================================================================
try:
    w = c.post("/api/v1/attendance/sessions/SESS-A/record", headers=H(fac_a_tok),
               json={"usn": "1MS21CS002", "room_id": "LH-101", "status": "PRESENT",
                     "source": "manual"})
    logs = c.get("/api/v1/admin/audit-logs", headers=H(admin_tok),
                 params={"action": "ATTENDANCE_RECORD" if w.status_code == 201 else "ATTENDANCE_UPSERT"}).json()
    items = logs.get("items", [])
    roles = {str(i.get("actor_role")) for i in items}
    rec("D13", "audit records carry the actor role for attendance writes", "low",
        "SECURE" if items and roles != {"None"} else "VULNERABLE",
        f"write={w.status_code} records={len(items)} actor_roles={sorted(roles)}")
except Exception as exc:
    rec("D13", "audit actor_role", "low", "ERROR", str(exc))

# ===========================================================================
# D14 - unversioned router parity
# ===========================================================================
try:
    a = c.get("/api/attendance/sessions/SESS-A", headers=H(fac_b_tok))
    b = c.get("/api/v1/attendance/sessions/SESS-A", headers=H(fac_b_tok))
    rec("D14", "unversioned /api routers enforce the same scope", "high",
        "SECURE" if a.status_code == b.status_code == 403 else "VULNERABLE",
        f"/api={a.status_code} /api/v1={b.status_code}")
except Exception as exc:
    rec("D14", "router parity", "high", "ERROR", str(exc))

# ===========================================================================
# D15 - admin login fail-closed without ADMIN_KEY
# ===========================================================================
try:
    missing = login(mk("198.51.100.75"), "admin1")
    wrong = login(mk("198.51.100.76"), "admin1", ADMIN_KEY and "wrong-admin-key")
    rec("D15", "ADMIN login requires a correct ADMIN_KEY", "critical",
        "SECURE" if missing.status_code == 401 and wrong.status_code == 401 else "VULNERABLE",
        f"no_key={missing.status_code} wrong_key={wrong.status_code}")
except Exception as exc:
    rec("D15", "admin key gate", "critical", "ERROR", str(exc))

# ===========================================================================
# D16 - MFA fails closed without an encryption key
# ===========================================================================
try:
    saved = os.environ.pop("MFA_ENCRYPTION_KEY", None)
    r = c.post("/api/v1/auth/mfa/enable", headers=H(fac_a_tok),
               json={"current_password": PW})
    if saved:
        os.environ["MFA_ENCRYPTION_KEY"] = saved
    rec("D16", "MFA enrollment fails closed without an encryption key", "high",
        "SECURE" if r.status_code == 403 else "VULNERABLE", f"HTTP {r.status_code}")
except Exception as exc:
    rec("D16", "MFA fail-closed", "high", "ERROR", str(exc))

# ===========================================================================
# D17 - upload parse cost (bounded) and CSV bomb shape
# ===========================================================================
try:
    cu = mk("198.51.100.77")
    rows = b"usn,status,room_id\n" + b"".join(
        b"1MS21C%05d,PRESENT,LH-101\n" % i for i in range(40000)
    )
    t0 = time.perf_counter()
    r = cu.post("/api/v1/agent/process-file", headers=H(fac_a_tok),
                files={"file": ("bomb.csv", rows, "text/csv")})
    elapsed = round(time.perf_counter() - t0, 2)
    rec("D17", "large CSV upload cost (1 MB / 40k rows)", "low",
        "INFO", f"HTTP {r.status_code} in {elapsed}s, {len(rows)} bytes")
except Exception as exc:
    rec("D17", "upload cost", "low", "INFO", str(exc)[:120])

# ===========================================================================
# D18 - invalid attendance status / confidence tampering
# ===========================================================================
try:
    bad = c.post("/api/v1/attendance/sessions/SESS-A/record", headers=H(fac_a_tok),
                 json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "HACKED",
                       "source": "manual"}, params={"upsert": "true"})
    conf = c.post("/api/v1/attendance/sessions/SESS-A/record", headers=H(fac_a_tok),
                  json={"usn": "1MS21CS001", "room_id": "LH-101", "status": "PRESENT",
                        "source": "manual", "confidence": 999}, params={"upsert": "true"})
    rec("D18", "invalid status and out-of-range confidence rejected", "medium",
        "SECURE" if bad.status_code in (400, 422) and conf.status_code in (400, 422)
        else "VULNERABLE",
        f"bad_status={bad.status_code} confidence_999={conf.status_code}")
except Exception as exc:
    rec("D18", "attendance value tampering", "medium", "ERROR", str(exc))

# ===========================================================================
# Summary
# ===========================================================================
print("=" * 100)
counts: dict[str, int] = {}
for _, _, _, verdict, _ in RESULTS:
    counts[verdict] = counts.get(verdict, 0) + 1
print("SUMMARY", counts)
for pid, name, severity, verdict, detail in RESULTS:
    if verdict in ("VULNERABLE", "BROKEN", "ERROR"):
        print(f"  {verdict:10s} {pid:5s} [{severity}] {name} :: {detail}")
print("=" * 100)
