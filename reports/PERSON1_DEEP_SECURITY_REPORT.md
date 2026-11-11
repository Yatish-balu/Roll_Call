# RollCall AI — Person 1 Hard Security Test Report (Round 2)

**Owner scope:** FastAPI → Authentication → MFA → Password Reset → Rate Limiting → Upload Security → API Authorization → Attendance Security.
**Date:** 2026-11-11
**Method:** Fresh adversarial angles (not a re-run of round 1) plus a full regression of round 1 on the current 700-test commit. Real HTTP against the app on a disposable database; 18 new probes in `scripts/person1_deep_suite.py`, 51 regression probes in `scripts/person1_attack_suite.py`.
**Test suite state:** `python -m pytest backend/tests -q` → **700 passed, 2 skipped** (exit 0).

## Headline

Round 1 findings are **all still open** — Person 1's modules were not modified by the Person 2 delivery. Four **new** defects were found by the deeper attacks: bcrypt truncation, Excel formula injection, unbound refresh tokens, and a password-policy gap that makes the truncation actionable.

| Suite | Probes | Held | Vulnerable | Broken | Info |
|---|---|---|---|---|---|
| Round 2 deep (new angles) | 18 | 13 | 4 | 0 | 1 |
| Round 1 regression | 51 | 32 | 15 | 1 | 3 |

---

## 1. Priority-ranked open findings

### P0 — Critical

**P0-1. MFA is never enforced at login.** `mfa_enabled=1` account → `HTTP 200` with password only (`P2.1`). `LoginRequest` has no code field; `login()` never reads `mfa_secret`. Enrolled MFA provides zero protection.

**P0-2. AI query tool SQL scope bypass via quoted identifiers.** `SELECT … FROM "attendance"` and `FROM [attendance]` return **SESS-A and SESS-B** to a caller scoped to SESS-B (`P7.2`, `P7.3`). Both `validate_read_only_sql` and `_apply_scope_to_sql` match only unquoted names, so the allowlist *and* the scope predicate are skipped. `query_tool` is deliberately allowed for VIEWER, so the weakest role has this read path.

### P1 — High

**P1-1. Cross-user session revocation (IDOR).** Faculty revoked an ADMIN session → `200` (`P4.6`). No `session.user_id` comparison.

**P1-2. Lockout is a DoS engine (three parts).**
- Correct password after 5 failures → `429` (`P3.2`).
- 22 unknown-user attempts → 17×`429`, then a valid login → `429`; success never clears `LoginAttempt` IP rows (`P3.4`).
- `time.sleep()` runs inside `_login_rate_lock`: `0.04 → 0.82 s` per attempt, serialising all logins (`P3.3`). Behind the new reverse proxy this becomes institution-wide.
- *Positive:* the concurrency race is closed — 8 parallel attempts produced exactly 5×`401` + 3×`429` (`D11`).

**P1-3. Unlimited password guessing on authenticated endpoints.** 15/15 wrong passwords on `/auth/mfa/enable` (`422`) and `/auth/password/change` (`401`), no `429` (`P2.3`, `P2.4`).

**P1-4. `/auth/sessions/revoke-all` → 500** (`P4.7`): `AuthRefreshToken.user_id` does not exist, so users cannot evict a compromised device.

### P2 — Medium (new in round 2)

**P2-1. bcrypt 72-byte truncation is reachable through the password policy** (`D1`, `D2`).
A user whose password is 72×`A` authenticated with `72×A + "TOTALLY-DIFFERENT-TAIL"` → `200`. Changing a password to 72×`B` + tail also succeeds, and a *different* tail authenticates. Policy allows unlimited-length passwords, so the ignored tail silently promises entropy that does not exist.
**Fix:** reject `len(password.encode("utf-8")) > 72` with a clear 422, or pre-hash (`base64(sha256(password))`) before bcrypt and version the hash format. Apply to change, reset and any admin seeding path.

**P2-2. CSV/Excel formula injection through report export** (`D12`).
Creating a student named `=HYPERLINK("http://evil.example/x","click")` and exporting the session produced a workbook with **1 live formula cell** (`data_type == "f"`). Opening the report in Excel executes the formula (payload could be `=cmd|' /C calc'!A0` or a data-exfiltration URL).
**Fix:** neutralise any cell value starting with `= + - @` (or tab/CR) by prefixing `'` in `export_tool` before writing, and validate student/room/subject names at creation. Add a test asserting no `data_type == "f"` cells for user-controlled fields.

**P2-3. Refresh tokens have no client binding** (`D9`).
A stolen `rollcall_refresh_token` replayed from a different IP/User-Agent → `200`. Rotation and reuse detection work, but theft from a different machine is invisible.
**Fix:** store `user_agent` + `ip_address` on the session (already columns) and either bind the refresh to a stable fingerprint hash or raise a security event + require re-auth when the fingerprint changes. Do not hard-fail on mobile networks without a grace path.

**P2-4. Username enumeration via login timing** (`P3.5`): known `0.163 s` vs unknown `0.024 s` (Δ139 ms). Always run bcrypt against a dummy hash.

**P2-5. Deleted users keep access** (`P1.5`): token of a deleted row still `200` on `/auth/me`. Reject tokens whose `sub` has no `users` row; revoke sessions on delete/deactivate.

**P2-6. Password reset model.** Any FACULTY can trigger a reset for an ADMIN (`P8.1`); no self-service reset exists for a locked-out user; with `SMTP_HOST` unset the token is stored but never delivered. Make initiation unauthenticated + rate-limited, restrict cross-account resets, require a provider at startup, and make consumption atomic (`UPDATE … WHERE token=:h AND expires>:now`, check `rowcount`).

**P2-7. MFA re-enrollment hijack.** `/auth/mfa/enable` overwrites an active secret with only the password. Require a current TOTP/recovery code when `mfa_enabled == 1`.

**P2-8. No malware scanner.** Uploads are accepted unscanned (`NullMalwareScanner`); the runtime log states it explicitly. Configure ClamAV or quarantine + async scan; hard-fail in production when unavailable.

### P3 — Low

- `/health` discloses `environment`; `/docs`, `/redoc`, `/openapi.json` are public (135 KB schema) — `P9.1`–`P9.3`.
- Upload magic-byte/NUL inspection still covers only the first 64 KB (`P6.8`, `P6.9`); the prompt-injection scan is now full-file.
- `LimitScope.REFRESH` is defined but never applied; VIEWER cannot change its own password; `validate_jwt_secret_configuration` is defined twice in `app/auth/jwt.py`; `/auth/logout` is callable unauthenticated.
- 1 MB / 40k-row CSV upload parses in 1.38 s (`D17`) — bounded, but it is synchronous CPU per request; keep the 20/10 min upload quota.

---

## 2. Controls that held under the deeper attacks

| Probe | Attack | Result |
|---|---|---|
| `D3` | `kid: ../../../../etc/passwd` in the JWT header | ignored, `200`, no file read |
| `D4` | non-string `sub` (`["admin1"]`) | rejected `401` — "Subject must be a string" |
| `D5`/`D7` | SQLi in session path and USN path | `404` (parameterised) |
| `D6` | case-variant session id | `404`, no fuzzy match |
| `D8` | cross-faculty `PUT` / `bulk` / `reconcile` | `403`, `403`, `403` |
| `D10` | refresh with cookie issued before a password change | `401`, revoked |
| `D11` | 8 concurrent failures | quota held at 5 |
| `D13` | audit `actor_role` on attendance writes | `ADMIN`, `FACULTY` recorded |
| `D14` | `/api` vs `/api/v1` parity | both `403` for the same cross-faculty read |
| `D15` | ADMIN login without / with wrong `ADMIN_KEY` | `401`, `401` |
| `D16` | MFA enrollment with no encryption key | `403` fail-closed |
| `D18` | status `HACKED`, `confidence: 999` | `422`, `422` |

Round 1's 32 held controls also still hold (JWT forgery family, VIEWER write block, upload size/magic/traversal/bomb, refresh CSRF + rotation + reuse detection, reset token single-use/expiry, admin-only endpoints, attendance scope).

---

## 3. Recommended execution order

1. Enforce MFA at login (P0-1) — highest real-world risk.
2. Fix SQL scope parsing (P0-2) and remove the raw-SQL chat branch.
3. Session IDOR (P1-1) + `revoke-all` (P1-4) — both small.
4. Rebuild the login throttle (P1-2): no lockout of valid credentials, no sleeping under a lock, trusted-proxy IP, clear IP counters on success.
5. Rate-limit every password-verification path (P1-3).
6. bcrypt length policy (P2-1) + export formula neutralisation (P2-2).
7. Refresh binding (P2-3), constant-time login (P2-4), unknown-sub rejection (P2-5).
8. Reset redesign (P2-6), MFA re-enrollment gate (P2-7), malware scanning (P2-8).
9. Prod surface reduction and hygiene (P3).

**Acceptance:** `scripts/person1_attack_suite.py` and `scripts/person1_deep_suite.py` report zero VULNERABLE/BROKEN rows, `pytest` stays at 700+ passing, and the payloads above become permanent regression tests.
