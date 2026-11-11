# RollCall AI — Joint Security Audit Report (Person 1 + Person 2)

**Date:** 2026-11-11
**Scope:** Full 2-person security work division — authentication/backend (Person 1) and frontend/infrastructure/AI (Person 2), as extended by Person 2's delivered Phase 1–4 changes.
**Method:** Adversarial grey-box testing over real HTTP against the running FastAPI app on a disposable database, plus targeted review of every new security module. Person 1's 15 findings were re-tested to confirm they survived Person 2's changes.
**Harnesses (reproducible):**

```bash
cd Roll_Call
PYTHONPATH=backend python scripts/person1_attack_suite.py   # 51 probes
PYTHONPATH=backend python scripts/person2_attack_suite.py   # 33 probes
python -m pytest backend/tests -q                            # 688 passed, 2 skipped
```

**Results**

| Suite | Probes | Held | Vulnerable | Broken | Info |
|---|---|---|---|---|---|
| Person 1 (auth/backend) | 51 | 32 | 15 | 1 | 3 |
| Person 2 (headers/CORS/AI) | 33 | 21 | 9* | 1 | 2 |

\* 8 of Person 2's 9 "vulnerable" rows are Person 1 regression re-checks (MFA, SQL scope, session IDOR, revoke-all, lockout, `/health`, OpenAPI). Person 2's **own** new code produced **2 genuine findings** (C9, A4) plus 1 low (A3).

**Bottom line:** Person 2's delivered controls are real and correctly wired — headers land on success *and* error responses, HSTS is correctly scoped, CORS is exact-origin and blocks `null`/prefix/sibling-port attacks, and the AI role matrix is enforced in the live chat and upload paths. The two-person delivery has **two remaining critical gaps, both on the Person 1 side**, plus **one cross-owner control conflict introduced by Person 2's CORS allowlist** that will break the refresh/logout flow in a browser.

---

## 1. Priority-ranked open findings

| # | Priority | Finding | Owner | Evidence |
|---|---|---|---|---|
| 1 | **P0 Critical** | MFA is never enforced at login — enrolled accounts sign in with password alone | Person 1 | R1/P2.1: `mfa_enabled=1` → `HTTP 200`, no TOTP |
| 2 | **P0 Critical** | AI query tool SQL scope bypass via quoted identifiers → cross-faculty read (now reachable by VIEWER too) | Person 1 (+P2 touchpoint) | R2/P7.2/P7.3: `FROM "attendance"` returned SESS-A **and** SESS-B for a SESS-B-only scope |
| 3 | **P1 High** | CORS allowlist rejects the exact CSRF headers the backend requires | **Cross-owner** | C9: `X-Requested-With` preflight `400`, `X-RollCall-CSRF` preflight `400`; both mandatory per `_validate_csrf` |
| 4 | **P1 High** | Cross-user session revocation (IDOR) — any account can kill any session | Person 1 | R3/P4.6: faculty revoked ADMIN session → `200` |
| 5 | **P1 High** | Lockout/DoS cluster: victim lockout, shared-IP lockout, sleep under a global lock | Person 1 | R5/P3.2 `429` on valid password; P3.3 `0.04→0.83 s`; P3.4 17×429 then valid login `429` |
| 6 | **P1 High** | Unlimited password guessing on `/auth/mfa/enable` and `/auth/password/change` | Person 1 | P2.3 15/15 `422`; P2.4 15/15 `401`; no `429` |
| 7 | **P1 High** | `/auth/sessions/revoke-all` returns 500 — no user-facing session recovery | Person 1 | R4/P4.7 `HTTP 500` (`AuthRefreshToken.user_id` absent) |
| 8 | **P2 Medium** | Prompt-injection filter bypassed by 5/10 variants (synonyms, zero-width, fullwidth, base64, non-English) | Person 2 | A4: `blocked=5/10` |
| 9 | **P2 Medium** | Tokens of deleted/unknown users stay valid; `/auth/me` synthesises a profile | Person 1 | P1.5 `HTTP 200` |
| 10 | **P2 Medium** | Username enumeration via login timing (bcrypt only for real users) | Person 1 | P3.5 known `0.161 s` vs unknown `0.022 s` |
| 11 | **P2 Medium** | Password-reset model: any FACULTY can reset an ADMIN, no self-service, provider unconfigured | Person 1 | P8.1 `200`; runtime log *"no email provider is configured"* |
| 12 | **P2 Medium** | MFA re-enrollment hijack (password-only overwrite of an active secret) | Person 1 | Code review of `enable_mfa` |
| 13 | **P2 Medium** | No malware scanner — uploads accepted unscanned | Person 1 (Phase 2) | Runtime log *"the uploaded file was NOT scanned"* |
| 14 | **P3 Low** | AI tool policy is skipped entirely when `actor_role` is omitted (backward-compat path) | Person 2 | A3: `AttendanceAgent().registry.execute("query_tool")` bypasses the matrix |
| 15 | **P3 Low** | `/health` leaks environment; `/docs`, `/redoc`, `/openapi.json` public (135 KB schema) | Cross-owner | R7/R8/P9.1–P9.3 |
| 16 | **P3 Low** | Security headers can be globally disabled at runtime by one env var (production only warns) | Person 2 | `SECURITY_HEADERS_ENABLED=false` |
| 17 | **P3 Low** | Upload inspection is partial (first 64 KB only; image polyglot body not stripped) | Person 1 | P6.8/P6.9 |
| 18 | **P3 Low** | `LimitScope.REFRESH` unused; VIEWER cannot change own password; duplicate `validate_jwt_secret_configuration`; `actor_role` missing on some audit writes; logout unauthenticated | Person 1 | Code review |

---

## 2. Person 2 — what was actually verified (and holds)

All of the following were attacked and **passed**:

**HTTP headers (H1–H8)**
- `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`, `X-Frame-Options: DENY`, CSP, COOP, CORP present on **200, 401, 404 and 422** responses and on **CORS preflights** — the pure-ASGI middleware is correctly registered *outside* `CORSMiddleware`, which is the detail that usually breaks this.
- Strict API CSP (`default-src 'none'`, `frame-ancestors 'none'`) on `/health` and `/openapi.json`; relaxed CSP only on `/docs` and `/redoc`.
- HSTS absent in development/plain HTTP, present under `APP_ENV=production`, and present when the edge terminates TLS (`X-Forwarded-Proto: https`) — correct scope, no HSTS on plaintext dev.

**CORS (C1–C8)**
- Exact `ACAO` + `Allow-Credentials: true` for the configured origin; **no** `ACAO` for `https://evil.example`, `null`, `http://localhost:5173.evil.example` (suffix attack) or `http://localhost:5174` (sibling port).
- Preflight returns explicit method list (`GET, POST, PUT, PATCH, DELETE, OPTIONS`) with no `*`; `TRACE` → `400`; `X-Evil-Header` → `400`; preflight carries the security headers.

**AI authorization (A1–A2, A5–A8)**
- Role matrix is correct and least-privilege: `query_tool → VIEWER`, every other tool `→ FACULTY`; unknown roles fail closed.
- Enforcement happens **inside** `ToolRegistry.execute` before the handler, and the live chat/upload routers do pass `actor_role=current_user.role` (`routers/agent.py:145` and `:353`) — so the policy is not dead code.
- Chat input capped (5000 chars → `422`); chat responses leak neither prompt text nor provider secrets; embedded CSV instructions are logged and treated as data.

**Not verifiable in-repo:** the Nginx/Caddy TLS config, backup script, Promtail rules and CI workflow were reviewed only as files — no live host, certificate, Loki/CloudWatch endpoint or restore drill exists in this environment.

---

## 3. Detailed findings and recommended fixes

### P0-1 — MFA still not enforced at login (Person 1)

Unchanged from the Person 1 report. `login()` never reads `mfa_enabled`, and `LoginRequest` has no code field. Person 2's tool-level AI authorization therefore protects a system whose primary identity control is bypassable by password alone.

**Fix:** add `mfa_code` to `LoginRequest`; after `pw_matches`, if `mfa_enabled` decrypt the secret and `verify_totp(..., last_counter=user.mfa_last_counter)` (or consume a recovery code), persist the counter, then create the session. Rate-limit with `MFA_VERIFY`, keep the generic 401, and require MFA for all ADMIN/FACULTY accounts.

### P0-2 — Quoted-identifier SQL scope bypass is still live and now VIEWER-reachable (Person 1)

`validate_read_only_sql` and `_apply_scope_to_sql` both use `\b(?:FROM|JOIN)\s+([A-Za-z0-9_]+)`, so `FROM "attendance"` / `FROM [attendance]` escapes the allowlist *and* the scope injection. Re-tested after Person 2's changes: a faculty scoped to SESS-B sees **SESS-A and SESS-B**.

Person 2's policy makes this worse in one respect and neutral in another: `query_tool` is deliberately allowed for **VIEWER**, so the weakest authenticated role now has the same data-read path. The unquoted baseline (P7.1) is correctly scoped, so this is purely the identifier parser.

**Fix:** normalise identifiers (strip `"`, `'`, backticks, `[]`) before validation; reject schema-qualified or quoted names; parse with `sqlglot` and fail closed on any table you cannot prove scoped. Remove the raw-SQL branch from the chat tool (`query_type="sql"`) — the parameterised builders already scope correctly — and add regression tests for quoted/bracketed/CTE/derived-table forms.

### P1-1 — CORS allowlist vs the app's own CSRF requirement (cross-owner)

`DEFAULT_ALLOWED_HEADERS = [Accept, Authorization, Content-Type, Origin, X-Request-ID, X-CSRF-Token]`, but `app/routers/auth.py::_validate_csrf` **requires** `X-Requested-With` or `X-RollCall-CSRF` on `/auth/refresh` and `/auth/logout`. In a browser, the preflight for either header returns **400**, so the frontend cannot refresh its 15-minute token and cannot log out cleanly. The likely "fix" under pressure — adding `*` back — would regress the CORS hardening Person 2 just delivered.

**Fix (either, not both):**
1. Add `X-Requested-With` and `X-RollCall-CSRF` to `DEFAULT_ALLOWED_HEADERS`; or
2. Standardise on the already-allowed `X-CSRF-Token` and update `_validate_csrf` to accept it.

Add an end-to-end test that logs in, refreshes with the CSRF header, and logs out **through the browser-equivalent preflight**, so the two modules can never drift again. Document the header contract in `docs/SECURITY_OPERATIONS.md`.

### P1-2 — Session revocation IDOR (Person 1)

`revoke_user_session` never compares `session.user_id` to the caller. **Fix:** 404 unless the session belongs to the caller; test with two users.

### P1-3 — Login throttle is still a denial-of-service engine (Person 1)

Three re-confirmed behaviours: the correct password is refused after 5 failures (`429`); 20 failures from one IP block every user on it and a success does not clear those `LoginAttempt` rows; and `time.sleep()` runs inside `_login_rate_lock`, serialising all logins (measured `0.04 → 0.83 s`, up to 5 s). Behind the Nginx/Caddy proxy Person 2 just added, `request.client.host` is the proxy unless real-IP handling is configured — turning one attacker IP into an institution-wide outage.

**Fix:** never reject a *correct* credential; return `429` + `Retry-After` instead of sleeping; drop the global lock; resolve the client IP only from a trusted-proxy allowlist; clear IP-derived counters on success; add CAPTCHA/alerting after N failures instead of hard lockout.

### P1-4 — Unlimited password verification on authenticated endpoints (Person 1)

**Fix:** `check_limit(..., record_failure=True)` on `/mfa/enable`, `/mfa/disable`, `/password/change`.

### P1-5 — `revoke-all` 500 (Person 1)

**Fix:** revoke through the `AuthSession.session_id` subquery (the `complete_password_reset` pattern).

### P2-1 — Prompt-injection filter is bypassable (Person 2)

5 of 10 payloads reached the agent: `"disregard all prior directives"`, zero-width obfuscation (`Ig\u200bnore`), fullwidth unicode, base64, and non-English text. This is expected of a pattern blocklist and is **not** the security boundary — tool authorization and data scoping are — but it should not be presented as complete protection.

**Fix:** normalise input before matching (NFKC, strip zero-width/format characters, lowercase, collapse whitespace) and decode obvious base64/hex; expand the pattern set (directives, guidance, policy, guardrails, `ignore … rules`). Keep it as **telemetry + friction**, not as an authorization control. Add the 5 bypassing payloads to `test_person2_security.py` so the suite measures resistance rather than confirming the blocklist.

### P2-2 — Tool policy skipped when `actor_role` is omitted (Person 2)

`ToolRegistry` treats a missing `actor_role` as "internal, no policy". Any future call path that forgets to pass the role silently loses enforcement (the local Streamlit `ui.py` already builds `AttendanceAgent(db_target=...)` with no role — today that only affects read paths, but the precedent is the risk).

**Fix:** default to `Role.VIEWER` (fail closed) and require an explicit sentinel such as `actor_role=INTERNAL` for trusted internal use, so the unsafe path must be opted into by name.

### P2-3 — Deleted users keep API access (Person 1)

**Fix:** reject tokens whose `sub` has no `users` row (allow only an explicit Supabase issuer allowlist), and revoke sessions on deactivate/delete.

### P2-4 — Timing enumeration (Person 1)

**Fix:** always run bcrypt against a dummy hash before returning the generic 401.

### P2-5 — Password reset design (Person 1)

**Fix:** unauthenticated rate-limited initiation (so a locked-out user can actually reset), restrict faculty → admin resets, require a configured provider at startup in production, and make consumption atomic (`UPDATE … WHERE token_hash=:h AND expires>:now`, `rowcount == 1`).

### P2-6 — MFA re-enrollment hijack (Person 1)

**Fix:** require a current TOTP/recovery code when `mfa_enabled == 1`.

### P2-7 — No malware scanning (Person 1)

**Fix:** ClamAV via `MALWARE_SCAN_COMMAND`, or quarantine + async scan before parsing; hard-fail in production when unavailable.

### P3 — Surface reduction and hygiene

- Disable `/docs`, `/redoc`, `/openapi.json` in production and drop `environment`/`version` from `/health`. This also removes the need for the relaxed docs CSP in production and shrinks the schema Person 2's OpenAPI surface exposes.
- Remove the `SECURITY_HEADERS_ENABLED` kill switch in production (or make it a startup failure, not a warning).
- Scan the whole upload, not `first_chunk`; re-encode images through PIL after the dimension check to strip polyglot trailers.
- Apply `LimitScope.REFRESH`; allow VIEWER self-service password change; delete the duplicate `validate_jwt_secret_configuration` in `app/auth/jwt.py`; pass `actor_role` on all audit writes; require authentication on `/auth/logout`.

---

## 4. Cross-owner verification the plan asks for ("each tries to break the other's work")

| Direction | Attempt | Result |
|---|---|---|
| P2 → P1 | CORS restrictions vs CSRF header contract | **BROKEN** — preflight rejects the headers the API demands (C9) |
| P2 → P1 | Tool role matrix vs `query_tool` SQL path | Matrix holds, but the allowed path has an unpatched scope bypass (P0-2) |
| P2 → P1 | Untrusted-content detection vs upload pipeline | Detection logs only; upload still parses (by design) — no authorization impact |
| P1 → P2 | Headers on error/preflight paths | Holds on 200/401/404/422/preflight |
| P1 → P2 | HSTS scoping; origin bypass (`null`, suffix, sibling port) | Holds |
| P1 → P2 | Policy bypass by omitting `actor_role` | **BROKEN** — policy silently skipped (P3, A3) |

---

## 5. Test-suite quality (why 688 passing did not catch this)

- `test_person2_security.py` (46 tests) verifies the header/CORS/policy **happy paths** and asserts that *the exact payloads in the blocklist* are detected. It contains no bypass payloads, so A4 could never fail.
- `test_c1_c2_scope_and_audit_api.py` covers unquoted `SELECT … FROM attendance` scoping but no quoted/bracketed identifiers, so P0-2 could never fail.
- No test logs in, refreshes and logs out through a browser-equivalent preflight, so the C9 header-contract split was invisible.
- No test covers MFA-at-login, cross-user session revocation, or lockout behaviour — hence the Person 1 findings surviving a 688-test green run.
- The Person 1 test-isolation fix Person 2 applied is correct (the two previously failing `jwt` tests now reflect the operator `.env`), and the invalid `StarletteDeprecationWarning` filter is gone — the suite now starts without `-o filterwarnings=`.

**Recommendation:** adopt the two attack harnesses as CI gates. Treat any probe that flips from SECURE → VULNERABLE as a build failure, and add each newly confirmed finding's payload as a permanent regression test.

---

## 6. Release blockers

**Code (must fix before production):** P0-1, P0-2, P1-1, P1-2, P1-3, P1-5.

**Configuration (operator, cannot be fixed in-repo):**
- `APP_ENV=production`, `ALLOWED_ORIGINS=https://<frontend>` (no localhost), strong `JWT_SECRET`, `SECURITY_EVENT_LOG_FILE` on a shipped path.
- `SMTP_HOST` configured, or password reset silently does nothing.
- `MALWARE_SCAN_COMMAND` configured, or uploads are never scanned.
- Reverse proxy must pass the real client IP (else the login IP quota is a global lockout), and must not terminate TLS without `X-Forwarded-Proto: https` (else no HSTS).
- DNS + real certificate, installed Nginx/Caddy config, verified with `curl -sI https://<domain>/health`.
- Off-host encrypted backups + a completed restore drill; log shipping and alert routing.
- Do not expose the legacy Streamlit UI (`app/ui.py`) — it bypasses the React auth flow and builds the agent without an actor role.

**Acceptance criterion for the security sign-off:** both harnesses report zero VULNERABLE/BROKEN rows on the release commit, and the 688-test suite still passes.

---

## 7. Post-audit remediation (Person 2)

Added after the audit, on the remediation commit. The Person 2 findings and
hardening observations are closed; Person 1 findings remain open and are
untouched by these changes.

| Audit item | Status | Evidence |
| --- | --- | --- |
| P1-1 / C9 - CORS allowlist rejects the CSRF headers | Fixed | `DEFAULT_ALLOWED_HEADERS` includes `X-Requested-With` and `X-RollCall-CSRF`, and they are re-appended even when `ALLOWED_HEADERS` is customized. `test_login_refresh_logout_browser_cors_preflights` performs preflight + login + refresh + logout. Probe C9 now `SECURE`. |
| P2-1 / A4 - prompt-injection filter bypassable | Fixed | NFKC normalization, invisible/format-character stripping, lowercasing, Base64/hex decoding, expanded vocabulary and a multilingual rule. Probe A4: `blocked=10/10`. |
| P3 / A3 - tool policy skipped when `actor_role` omitted | Fixed | Missing/invalid roles default to `VIEWER` (fail closed). `TRUSTED_INTERNAL` is an opaque sentinel for internal jobs only; the Streamlit UI refuses to start in production. Probe A3 now `SECURE`. |
| Item 16 - headers can be disabled in production | Fixed | Production startup raises `RuntimeError`; the middleware force-enables headers when `APP_ENV=production`. |
| Item 17 - upload inspection limited to first 64 KB | Fixed | The upload endpoint inspects the complete bounded payload, and matching scans overlapping windows. Regression: `test_prompt_inspection_covers_payload_past_first_64kb_and_window`. |

Re-verification:

* `python -m pytest tests -q` -> **700 passed, 2 skipped**.
* `scripts/person2_attack_suite.py` -> all header, CORS (incl. C9) and AI
  (incl. A3/A4) probes `SECURE`; remaining `VULNERABLE`/`BROKEN` rows are the
  Person 1 findings R1, R2, R3, R4, R5, R7 and R8.

The acceptance criterion below ("zero VULNERABLE/BROKEN rows") still depends on
the Person 1 fixes; Person 2's own probes are clean.
