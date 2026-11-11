# RollCall AI — Person 1 Security Audit Report

**Scope:** Person 1 ownership per *Security Work Division 2-Person Implementation Plan* — Authentication, MFA, Password Reset, Rate Limiting, Upload Security, API Authorization, Attendance Security.
**Method:** Black/grey-box adversarial testing against the real FastAPI app over HTTP, on a disposable database, plus targeted code review.
**Date:** 2026-11-11
**Harness:** `scripts/person1_attack_suite.py` (reproducible: `cd Roll_Call && PYTHONPATH=backend python scripts/person1_attack_suite.py`)

**Result:** 51 probes → **32 controls held**, **15 vulnerabilities confirmed**, **1 broken control**, **3 informational**.

> Not covered here (Person 2 ownership): HTTPS/HSTS/CSP/security headers, CORS policy validation, prompt-injection, dependency CVEs, CDN/reverse-proxy config, monitoring. CORS was only incidentally exercised.

---

## 1. Priority summary

| # | Priority | Finding | Evidence | Owner file |
|---|----------|---------|----------|------------|
| 1 | **P0 Critical** | MFA is never enforced at login — enrolled accounts authenticate with password alone | P2.1: `mfa_enabled=1` account → `HTTP 200`, no TOTP requested | `app/routers/auth.py` (`login`) |
| 2 | **P0 Critical** | AI query tool SQL scope bypass via quoted identifiers → cross-faculty data read | P7.2/P7.3: `FROM "attendance"` / `FROM [attendance]` returned SESS-A **and** SESS-B for a faculty scoped to SESS-B only | `tools/query_tool.py` (`_TABLE_REF_RE`, `_apply_scope_to_sql`, `validate_read_only_sql`) |
| 3 | **P1 High** | Cross-user session revocation (IDOR) — any account can kill any other account's session | P4.6: faculty revoked an ADMIN session → `HTTP 200` | `app/routers/auth.py` (`revoke_user_session`) |
| 4 | **P1 High** | Account-lockout DoS — 5 failures lock the victim out; the *correct* password is then also rejected | P3.2: valid credentials → `HTTP 429` | `app/routers/auth.py` (`_check_rate_limit`, lock order) |
| 5 | **P1 High** | Shared-IP failure quota locks out **every** user behind that IP; a success does not clear it | P3.4: 22 unknown-user attempts → 17×429, then valid `fac_a` login → `HTTP 429` | `app/routers/auth.py` (`_check_rate_limit` on `LoginAttempt.ip_address`) |
| 6 | **P1 High** | Login holds a **process-wide lock while sleeping** → global login DoS / serialization | P3.3: per-attempt `0.02s → 0.82s` with `time.sleep()` inside `_login_rate_lock` | `app/routers/auth.py` (`login`, `_reject_login`) |
| 7 | **P1 High** | Unlimited password guessing on authenticated endpoints (no rate limit / lockout) | P2.3 (15/15 wrong on `/auth/mfa/enable`, no 429), P2.4 (15/15 on `/auth/password/change`) | `app/routers/auth.py` (`enable_mfa`, `change_password`, `disable_mfa`) |
| 8 | **P1 High** | `/auth/sessions/revoke-all` is broken (500) — users cannot respond to a compromised session | P4.7: `HTTP 500`; `AuthRefreshToken` has no `user_id` column | `app/routers/auth.py` (`revoke_all_other_sessions`) |
| 9 | **P2 Medium** | Username enumeration via login timing (bcrypt runs only for real accounts) | P3.5: known `0.180s` vs unknown `0.022s` (Δ 158 ms) | `app/routers/auth.py` (`login`, early return) |
| 10 | **P2 Medium** | Tokens for deleted/unknown users stay valid; `/auth/me` returns 200 and trusts token claims | P1.5: user row deleted, old token → `HTTP 200` | `app/auth/dependencies.py`, `app/routers/auth.py` |
| 11 | **P2 Medium** | Any FACULTY can trigger a password reset for an ADMIN; no self-service reset for a locked-out user; email provider unconfigured | P8.1: faculty → admin reset `HTTP 200`; log: *"DEPLOYMENT BLOCKER: no email provider configured"* | `app/routers/auth.py` (`initiate_password_reset`) |
| 12 | **P2 Medium** | MFA re-enrollment hijack — `/auth/mfa/enable` overwrites an existing secret with only the password | Code review (`enable_mfa`), enabled account | `app/routers/auth.py` |
| 13 | **P2 Medium** | No malware scanner configured — uploads are accepted unscanned | P6 run log: *"the uploaded file was NOT scanned"* | `app/security/uploads.py` (`NullMalwareScanner`) |
| 14 | **P3 Low** | `/health` discloses environment; `/docs`, `/redoc`, `/openapi.json` exposed unauthenticated (135 KB schema) | P9.1/P9.2/P9.3 | `app/main.py` |
| 15 | **P3 Low** | Fragmented upload inspection: NUL scan + magic check only on the first 64 KB; polyglot bodies not stripped | P6.8/P6.9 | `app/routers/agent.py` |
| 16 | **P3 Low** | `LimitScope.REFRESH` policy is defined but never applied to `/auth/refresh` | Code review | `app/routers/auth.py` (`refresh`) |
| 17 | **P3 Low** | VIEWER accounts cannot change their own password (403) | Code review (`change_password`) | `app/routers/auth.py` |
| 18 | **P3 Low** | `validate_jwt_secret_configuration` is defined twice; the second definition shadows the hardened first one | Code review (`app/auth/jwt.py`) | `app/auth/jwt.py` |
| 19 | **P3 Low** | Session/subject audit entries omit `actor_role`, weakening audit filtering and chain completeness | Code review (`sessions.py`, `admin.py`) | `app/routers/sessions.py`, `app/routers/admin.py` |
| 20 | **P3 Low** | `/auth/logout` is callable unauthenticated | P4.8 → `HTTP 200` | `app/routers/auth.py` |

---

## 2. Control verification — what actually held up

These attacks were attempted and **blocked** (32 probes):

- **JWT forgery:** `alg=none`, token signed with the committed dev fallback, `user_metadata.role=ADMIN` escalation, expired token replay → all `401/403`. No `alg` confusion, no metadata trust.
- **RBAC:** VIEWER blocked from attendance write, attendance delete, student create, file upload (`403`×4). Faculty blocked from `/admin/audit-logs` and `/admin/teacher-subjects`.
- **Cross-faculty attendance/session/analytics access:** write, session read, metadata read, analytics summary, student attendance history → `403/404` (existence hidden).
- **Attendance tampering:** body-vs-path `session_id` mismatch → `400`; USN `"  1ms21cs001  "` normalized to `1MS21CS001`; duplicate/bulk guards intact.
- **Session lifecycle:** refresh without CSRF header → `403`; foreign `Origin` → `403`; token rotation works; replayed refresh token → `401 TOKEN_REUSED` and the whole family (including the new token) is revoked.
- **Password reset token:** single-use enforced (`200` then `400`), expired token rejected (`400`), token never returned by the API.
- **Uploads:** >10 MB → `413`; MZ-in-CSV → `400`; JPEG-bytes-named-`.png` → `400`; `.exe` → `400`; empty → `400`; path-traversal filename → no file written outside the temp dir; 30000×30000 PNG → `400`.
- **Per-account lockout** does trigger (6th attempt `429`); **admin** login fails closed when `ADMIN_KEY` is absent/blank and uses constant-time comparison.

---

## 3. Detailed findings and recommended fixes

### P0-1 — MFA is decorative: login never checks it

`login()` verifies the password and immediately issues a session + JWT. `user.mfa_enabled` is never read, `mfa_secret` is never used, and no second factor is accepted by the request schema (`LoginRequest` has only `user_id`, `password`, `admin_key`, `remember_me`). Enrollment endpoints (`/auth/mfa/enable`, `/mfa/verify`) work, so users *believe* they are protected while a stolen password is sufficient. This defeats the entire Phase-1 MFA objective.

**Fix**
1. Add `mfa_code: Optional[str]` to `LoginRequest`.
2. In `login()`, after `pw_matches`, if `user.mfa_enabled`: decrypt the secret, call `verify_totp(..., last_counter=user.mfa_last_counter)` (or consume a recovery code), persist `mfa_last_counter`, and only then create the session. Accept a numeric code **or** a recovery code; never accept an empty one.
3. Apply `LintScope.MFA_VERIFY` limiting here too (currently only on enrollment).
4. Return the generic `401` for a wrong code — do not reveal MFA state. If the frontend needs a two-step flow, return an opaque, short-lived, single-use `mfa_ticket` (not a session) after the password step.
5. Require MFA for every `ADMIN`/`FACULTY` account as policy, and add a startup warning when an active privileged account has `mfa_enabled=0`.

### P0-2 — SQL scope bypass in the AI query tool

`validate_read_only_sql()` extracts tables with `\b(?:FROM|JOIN)\s+([a-zA-Z0-9_]+)`. A quoted identifier (`FROM "attendance"`, `FROM [attendance]`, backticks) does not match, so the allowlist is bypassed. `_apply_scope_to_sql()` uses the same unquoted-only regex to inject the `session_id` predicate, so the scope filter is also skipped. Result: a faculty member scoped to one session reads every session and student via `SELECT * FROM "attendance"`.

Reachability is real: `app/agent.py` registers the query tool as `query_tool(query_type=..., scope=self.scope, **kwargs)` and `tools/query_tool.py` dispatches `query_type in ("sql","custom_sql")` to `safe_sql_query`, so an LLM-chosen `sql` argument reaches this path from `POST /agent/chat`. The same weakness means a future non-AI caller is unsafe too.

**Fix**
1. Normalise identifiers before validation: strip `"`, `'`, `` ` ``, `[`, `]`, and reject anything containing quotes, dots, or whitespace after `FROM|JOIN` (schema-qualified names must be rejected, not silently ignored).
2. Replace regex scoping with a real parser (e.g. `sqlglot`): parse the statement, walk every `Table` node, and **reject the query** if any table is not in the allowlist or cannot be rewritten.
3. Fail closed: if a table reference cannot be proven scoped, refuse the query instead of executing it unscoped.
4. Better still, drop the raw-SQL path from the chat tool entirely and expose only the parameterised builders (`query_attendance`, `query_students`, `query_session_stats`), which already scope correctly.
5. Add regression tests for quoted, bracketed, schema-qualified, CTE and derived-table references.

### P1 — Cross-user session revocation (IDOR)

`revoke_user_session()` loads `AuthSession` by path id and revokes it without comparing `session.user_id` to `current_user.user_id`. Any authenticated user (including VIEWER) can revoke an administrator's session, forcing logout at will and disrupting incident response.

**Fix:** after `db.get(...)`, `if session is None or session.user_id != current_user.user_id: raise HTTPException(404)` — 404 (not 403) so other users' session IDs are not confirmed. Add a test with two users.

### P1 — Lockout/DoS cluster (three related flaws)

1. **Victim lockout:** `_check_rate_limit` refuses the request *before* the credential check, so after 5 failures the legitimate user cannot log in for 10 minutes. An attacker can keep any account locked indefinitely with 1 request/minute.
2. **Shared-IP lockout:** `LoginAttempt.ip_address` failures are counted with no per-user key for unknown accounts, so 20 failures from one IP block **every** user on it, and `clear_limit()` on success only clears `security_rate_limits`, never these `LoginAttempt` rows. Behind a reverse proxy `request.client.host` is the proxy, so this becomes an institution-wide outage from one attacker (and one botnet IP = one lockout event per minute).
3. **Global lock + sleep:** `_reject_login` calls `time.sleep(failure.delay_seconds)` while holding `_login_rate_lock`, serialising every login in the process. Measured 0.02 → 0.82 s and growing to 5 s.

**Fix**
- Never block a *correct* credential: apply the counter check, then verify the password, and only return `429` if the credentials were also wrong (or return a challenge/CAPTCHA after N failures).
- Replace sleeping with an immediate `429` + `Retry-After`; the delay must never run under a shared lock. Remove `_login_rate_lock` entirely — the DB/Redis counters are already atomic.
- Key the IP quota on a *trusted* client IP (explicit `TRUSTED_PROXY`/`ProxyHeaders` allowlist), keep a generous IP quota, and clear `LoginAttempt`-derived IP counters on successful authentication.
- Prefer progressive backoff keyed on `(account, IP)` plus alerting over hard account lockout.

### P1 — Rate limiting missing on password-verification endpoints

`enable_mfa`, `change_password`, `disable_mfa` all call `bcrypt.checkpw` with no limiter. 15/15 wrong guesses were accepted with no `429`. Anyone holding a stolen access token (or a malicious insider) gets an unlimited offline-speed password oracle.

**Fix:** wrap each in `check_limit(db, LimitScope.MFA_VERIFY or a new `PASSWORD_VERIFY`, f"user:{id}", record_failure=True)` / `f"ip:{ip}"`, and log `password_verification_failed` events.

### P1 — `revoke-all` is broken

`revoke_all_other_sessions` executes `update(AuthRefreshToken).where(AuthRefreshToken.user_id == ...)`, but the model has no `user_id` column → `AttributeError` → `500`. The endpoint is the main user-facing remediation for a stolen device.

**Fix:** revoke refresh tokens via a subquery on `AuthSession.session_id` for that user (same pattern already used in `complete_password_reset`), then add a test.

### P2 — Timing-based username enumeration

Unknown users return before bcrypt (`0.022 s`), real users pay the hash cost (`0.180 s`). A 158 ms delta is trivially measurable.

**Fix:** always run one `bcrypt.checkpw` against a precomputed dummy hash (or a fake user with a random hash) before returning the generic `401`, and keep response bodies/headers identical.

### P2 — Deleted users keep access

`get_current_user` only enforces state when a local row exists; with no row it returns the token's claims, and `/auth/me` even synthesises a profile with `is_active=1`. Deleting an account does not revoke its tokens (up to 15 min, and refresh still works until 7 days if a session row survives).

**Fix:** reject tokens whose `sub` has no `users` row (allow only an explicit Supabase issuer allowlist), or maintain a revocation list/`users.deleted_at` check. Revoke all `AuthSession` rows when a user is deactivated/deleted, and re-check `is_active` at refresh (already done) **and** at every request.

### P2 — Password reset model is wrong for the stated goal

Reset is *not* self-service: it requires authentication and ADMIN/FACULTY, so the user who is locked out — the actual use case — cannot use it. Conversely, any FACULTY can trigger a reset for an ADMIN with no approval. With `SMTP_HOST` unset the token is generated and stored but never delivered (logged as a deployment blocker).

**Fix:** make initiation unauthenticated (rate-limited per account + IP, generic response), restrict cross-account resets (faculty → same department only, or admin approval), require a configured provider at startup in production, and make consumption atomic: `UPDATE users SET ... WHERE password_reset_token = :h AND password_reset_token_expires > :now` and check `rowcount == 1`.

### P2 — MFA re-enrollment hijack

`enable_mfa` overwrites `mfa_secret` and `mfa_recovery_codes` for an already-enrolled account with only the password. An attacker with a session + password silently replaces the victim's second factor.

**Fix:** when `mfa_enabled == 1`, require a current TOTP/recovery code (or an email confirmation) before re-enrollment; ratchet `mfa_last_counter`; emit an alert event.

### P2 — No malware scanning

`NullMalwareScanner` returns `clean=True, available=False`; every upload is accepted unscanned and only logged. This is honest but not protective.

**Fix:** run ClamAV (`MALWARE_SCAN_COMMAND`) in the deploy, or move uploads to a quarantine bucket and scan asynchronously before parsing. Treat "scanner unavailable" as a configurable hard fail in production.

### P3 — Hardening and hygiene

- Disable `/docs`, `/redoc`, `/openapi.json` in production (`docs_url=None`); remove `environment`/`version` from `/health` or restrict it.
- Inspect the whole upload, not just `first_chunk`: scan for NUL/binary signatures across chunks and re-encode images through PIL after the dimension check to strip polyglot trailers.
- Apply `LimitScope.REFRESH` to `/auth/refresh`.
- Allow VIEWER to change their own password (or document the restriction as intentional).
- Delete the duplicate `validate_jwt_secret_configuration` in `app/auth/jwt.py`; keep the hardened one (it is the only one enforcing the dev-fallback ban) and have `_validate_jwt_secret` point at it.
- Pass `actor_role` to `crud.create_audit_entry` in `sessions.py` and `admin.py`.
- Require authentication on `/auth/logout` (or at least a valid CSRF token + cookie, which it already requires).

---

## 4. Verification gaps in the existing test suite

1. `python -m pytest backend/tests/...` fails to start: `pytest.ini` filters `starlette.exceptions.StarletteDeprecationWarning`, which does not exist in the installed Starlette. Workaround used: `-o filterwarnings=`.
2. Baseline of the Person 1 suites: **72 passed, 2 failed**.
   - `test_person1_security.py::test_jwt_secret_matrix`
   - `test_security_regression.py::test_production_environment_rejects_insecure_dev_secret`
   Both failures are **test-isolation artifacts**, not vulnerabilities: the repo `.env` provides a 48-char `JWT_SECRET`, so `patch.dict(..., {"JWT_SECRET_KEY": ""})` cannot force the production branch (`get_jwt_secret` reads `JWT_SECRET` first). Fix by `monkeypatch.delenv("JWT_SECRET", raising=False)` in those tests so the suite is honest about what it proves.
3. None of the 15 confirmed findings above is covered by an existing test — the suite tests the happy path of each control but not identifier quoting, cross-user session revocation, MFA-at-login, or lockout behaviour.

---

## 5. Recommended execution order (Person 1)

1. **Enforce MFA at login** (P0-1) — highest real-world risk.
2. **Fix SQL scope rewriting / remove raw-SQL chat path** (P0-2).
3. **Session revocation IDOR + broken `revoke-all`** (P1) — one-line ownership check, one query fix.
4. **Rework the login throttle** (P1): no sleeping under a lock, no lockout of valid credentials, trusted-proxy IP resolution, clear IP counters on success.
5. **Rate-limit every password-verification path** (P1).
6. **Constant-time login + reject tokens without a user row** (P2).
7. **Password-reset redesign + atomic consumption + provider startup check** (P2).
8. **Upload hardening + malware scanning in the deploy** (P2/P3).
9. **Prod surface reduction** (docs/openapi/health), audit `actor_role`, `jwt.py` dedupe (P3).
10. **Then** joint regression with Person 2 (CORS/headers/AI) and a re-run of this harness — the 15 findings currently marked VULNERABLE are the acceptance criteria.

---

## 6. Deployment blockers (block production, independent of code)

- `SMTP_HOST` unset → password reset is undeliverable while reporting success.
- `MALWARE_SCAN_COMMAND` unset → uploads are never scanned.
- `REDIS_URL` unset → limiter runs on the shared DB table (acceptable single-cluster, but the `security_rate_limits` table must exist — migration 0016 — or the limiter silently degrades to per-process counters).
- Reverse proxy must be configured to present the real client address, otherwise the IP quota becomes a global lockout.
