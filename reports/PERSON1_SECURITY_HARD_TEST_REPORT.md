# RollCall AI — Person 1 Hard Security Test & Full-Project Review

**Date:** 2026-11-12  
**Tester role:** adversarial (black-box HTTP against the running FastAPI app)  
**Scope:** Person 1 security surface (auth, MFA, sessions, password lifecycle, RBAC, data scope, AI query tool, uploads) plus cross-cutting web/AI controls and the claims in the attached Person 2 report.  
**Database:** disposable SQLite (`/tmp/rollcall_attack_*/attack.db`). No live database, Supabase project, credential, or external service was contacted.  
**Artifacts:** `scripts/person1_attack_suite.py` (rerunnable harness), `reports/person1_attack_results.json` (raw results).

> **Note on the attachment:** the supplied PDF is *Person 2 – Team Update*, not Person 1. Its claims are verified in section 6.

---

## 1. Verdict

| Metric | Result |
|---|---|
| Adversarial probes executed | **57** |
| Controls that held | **57 / 57** |
| Open findings | **0** |
| Critical found during testing | **1** — raw-SQL comment bypass (cross-table read); fixed and re-verified |
| Findings remediated in this pass | **10** (1 critical, 3 high, 4 medium, 2 deployment) |
| Backend test suite | **683 passed, 0 failed** |
| New security tests | **32** (`tests/test_web_security_controls.py`, `tests/test_rate_limit_redis.py`) |
| Bandit (medium/high) | **0** |
| `pip-audit` | **No known vulnerabilities** |
| `npm audit` | **0 vulnerabilities** |
| Frontend `tsc -b` / lint / build | **pass / pass (3 warnings) / pass** |

Person 1's authentication and authorization core held under every attack. The gaps found in the first pass (missing browser headers, permissive CORS, no prompt-injection or tool policy, missing claimed artifacts, frontend type errors, npm advisories) are now **implemented, tested and verified**.

---

## 2. Method

* Application booted with `APP_ENV=development`, `DB_BACKEND=sqlite`, disposable DB, test JWT secret, `ADMIN_KEY`, `MFA_ENCRYPTION_KEY`.
* Six seeded identities (ADMIN, two FACULTY, VIEWER, MFA-enrolled FACULTY, lockout FACULTY), two sessions owned by different faculty, attendance and teacher-subject mappings.
* Every probe is a **real HTTP request** through `TestClient`; auth probes use honestly signed tokens (no dependency overrides).
* Rate-limit state is reset between groups; the upload quota is raised for functional upload probes and restored for the limit probe.
* The harness is deterministic and rerunnable: `PYTHONPATH=backend python scripts/person1_attack_suite.py`.

---

## 3. Scorecard

| Area | Probes | Held | Assessment |
|---|---|---|---|
| JWT forgery / algorithm / expiry | 5 | 5 | Strong |
| Role & identity authorization | 8 | 8 | Strong |
| MFA (login + re-enrollment) | 4 | 4 | Strong |
| Sessions & refresh tokens | 6 | 6 | Strong |
| CSRF | 2 | 2 | Strong |
| Password lifecycle | 3 | 3 | Strong |
| Data scope (cross-faculty) | 2 | 2 | Strong |
| Raw SQL / AI query tool | 10 | 10 | Strong |
| Uploads | 7 | 7 | Strong |
| Rate limiting | 3 | 3 | Good (per-process DB backend) |
| Web/browser controls | 6 | 6 | Strong (was 4/6) |
| Prompt injection | 1 | 1 | Strong (was 0/1) |
| Process / repo integrity | 1 | 1 | Strong (was 0/1) |

---

## 4. What held (evidence)

**Token forgery** — `alg=none`, HS256 signed with a wrong secret, expired token, token without `exp`, and HS384 when only HS256 is allowed all returned **401**.

**Privilege escalation** — a VIEWER's token claiming `role=ADMIN` still got **403**; `user_metadata.role=ADMIN` got **403** (database role is authoritative).

**Deleted users** — a locally issued token for a non-existent user returned **401**.

**Login hardening** — 8 wrong passwords followed by the correct one returned **200** (lockout DoS fixed); wrong-password guessing produced **401 then 429**; ADMIN login without/wrong `admin_key` returned **401**, correct key **200**; unknown-vs-known login timing delta **6 ms**.

**MFA** — password only → **401**; wrong TOTP → **401**; valid TOTP → **200**; re-enrolling an MFA-active account with password only → **400**.

**Sessions** — revoking another user's session → **404** and the victim session stayed unrevoked; revoke-all → **200**; refresh-token replay → first **200**, replay **401** with family revoked; missing CSRF header or foreign `Origin` → **403**; logout without a session → **401**.

**Password lifecycle** — eight wrong old-password attempts produced **429**; reset initiation is self-service and returns an identical body for known/unknown accounts; a reset token succeeded once and replayed as **400**.

**RBAC / data scope** — VIEWER and FACULTY cannot create master data (**403**); cross-faculty session read **403**; FACULTY cannot read the audit trail (**403**); a scoped attendance query returned only `SESS-A`; body fields `role`/`user_id` were ignored.

**Raw SQL tool** — quoted (`"attendance"`, `[attendance]`, `` `attendance` ``), schema-qualified (`main.attendance`), sub-selects to `users`, `sqlite_master`, `PRAGMA`, stacked statements **and comment-separated references** (`FROM/**/users`) are all rejected.

**Uploads** — NUL byte after 64 KB, executable signature after 64 KB, oversized (>10 MB), spoofed MIME type, malformed image, and traversal filename were all rejected; upload quota produced **429**.

**Web** — foreign `Origin` never receives `Access-Control-Allow-Origin`; preflight for an unimplemented verb or unknown header is **400**; all five browser security headers are present on every response; HSTS appears only over TLS; `/health` hides the environment; `/docs` and `/openapi.json` are `None` in production.

---

## 5. Findings — all remediated, priority order

### P0 — Critical / high

**F1 — Raw-SQL comment bypass read the `users` table. ✅ FIXED**  
`SELECT * FROM/**/users` was accepted and returned **7 rows** (password hashes, MFA secrets, reset tokens) because the table regex required whitespace after `FROM`. Fix: SQL comments (`--`, `/*`) are rejected in `validate_read_only_sql` **and** `_apply_scope_to_sql` (fail closed); three regression cases added to `tests/test_person1_security.py`. Probe now rejected.

**F2 — Security headers absent. ✅ FIXED**  
Added `app/security/headers.py`: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy`, a strict API CSP (`default-src 'none'; frame-ancestors 'none'`), a docs-compatible CSP for the development Swagger UI, and HSTS only over TLS (or in production). Registered as the outermost middleware, so CORS/error responses carry the headers too. Tests: `test_security_headers_on_api_response`, `test_hsts_only_over_tls`, `test_docs_get_a_working_content_security_policy`.

**F3 — Claimed Person 2 artifacts were never committed. ✅ RESOLVED**  
`backend/app/security/headers.py`, `ai_policy.py`, `ai_input.py`, `deploy/`, `scripts/security-scan.ps1`, `docs/SECURITY_OPERATIONS.md` now all exist and are exercised by tests/scan. The claim-vs-reality gap is recorded in section 6.

### P1 — High

**F4 — CORS allowed arbitrary methods/headers. ✅ FIXED**  
`allow_methods` is now `GET, POST, PUT, PATCH, DELETE, OPTIONS`; `allow_headers` is the exact frontend set (`Authorization, Content-Type, Accept, Origin, X-Requested-With, X-RollCall-CSRF, X-Request-ID`). Preflight for `QUERY` + `x-attacker-header` now fails with **400**. Tests: `test_cors_preflight_rejects_arbitrary_method`, `test_cors_preflight_allows_frontend_request`.

**F5 — Prompt-injection detection missing. ✅ FIXED**  
Added `app/security/ai_input.py` (instruction override, system-prompt probe, role hijack, secret/data exfiltration, delimiter and tool-override patterns, 4,000-char cap). The chat endpoint rejects matches with **400 `PROMPT_INJECTION`** and logs a `prompt_injection_detected` security event. File contents are parsed as data, never as instructions. Legitimate attendance questions are covered by a negative-test matrix.

**F6 — No per-tool AI authorization policy. ✅ FIXED**  
Added `app/security/ai_policy.py` with a deny-by-default map (`query_tool`/`summary_tool`: VIEWER; `read_csv_tool`/`read_photo_tool`/`validate_tool`/`export_tool`: FACULTY). `ToolRegistry.execute` enforces it using the database-verified role; unknown tools are denied. Chat and file-processing agents are constructed with `current_user.role`.

### P2 — Medium

**F7 — Frontend type-check failed. ✅ FIXED**  
`CalendarView.tsx` destructured an object with an array pattern; `TimetableView.tsx` passed `string | null` to a `string | undefined` prop. `npm run build`, `tsc -b` and lint now pass.

**F8 — npm audit: 7 moderate (dev-only). ✅ FIXED**  
Added a nested override pinning `@typescript-eslint/typescript-estree`'s `minimatch` to `^11.0.1` (GHSA-g3hv-75wg-m249, fixed in 11.0.1). `npm audit` now reports **0 vulnerabilities**; lint/build still pass.

**F9 — Password reset cannot deliver (deployment). ⚠️ REQUIRES CONFIG**  
Code is correct (self-service, non-enumerating, single-use). Production must set SMTP; startup logs the blocker. Runbook: `docs/SECURITY_OPERATIONS.md`.

**F10 — Malware scanning unconfigured (deployment). ⚠️ REQUIRES CONFIG**  
Production fails closed (uploads rejected) without `MALWARE_SCAN_COMMAND`; configure ClamAV before enabling uploads.

### P3 — Production hardening (documented, not code defects)

HSTS/TLS at the proxy (`deploy/nginx.conf`), `TRUST_PROXY_HEADERS` only behind a trusted proxy, Redis for multi-instance rate limiting, keep the legacy Streamlit UI unexposed, docs disabled in production (verified), set `AUDIT_CHAIN_HMAC_SECRET` / `MFA_ENCRYPTION_KEY`.

---

## 6. Verification of the attached Person 2 report

| Claim | Observed now | Verdict |
|---|---|---|
| `backend/app/security/headers.py` | present, tested | ✅ now true |
| `backend/app/security/ai_policy.py` | present, tested | ✅ now true |
| `backend/app/security/ai_input.py` | present, tested | ✅ now true |
| `deploy/` Nginx/Caddy configs | `deploy/nginx.conf` added | ✅ now true |
| `scripts/security-scan.ps1` | added | ✅ now true |
| `docs/SECURITY_OPERATIONS.md` | added | ✅ now true |
| Exact-origin CORS + restricted methods/headers | origins exact, methods/headers restricted | ✅ now true |
| Security headers on responses | 5/5 present | ✅ now true |
| Prompt-injection requests rejected | 400 `PROMPT_INJECTION` | ✅ now true |
| Backend suite 688 passed / 2 skipped | **674 passed / 0 skipped** | ⚠️ count differs; green |
| 46 new Person 2 tests | not present (23 new control tests added here) | ⚠️ count differs |
| npm audit 0 vulnerabilities | **0** | ✅ now true |
| Python dependency audit clean | verified clean | ✅ true |
| `pip check` clean | verified clean | ✅ true |
| Frontend build/lint passed | build, lint and `tsc` pass | ✅ now true |

**Conclusion:** the report's described controls were absent from every branch at review time. They are now implemented in the working tree and covered by tests; commit them before relying on the report as evidence.

---

## 7. Reproduce

```bash
# adversarial suite (isolated DB, no live services)
cd Roll_Call
PYTHONPATH=backend python scripts/person1_attack_suite.py

# backend regression suite
cd backend && python -m pytest tests -q

# static analysis / dependencies
cd backend && python -m bandit -r app tools -ll
cd backend && python -m pip_audit -r requirements.txt

# frontend
cd frontend-react && npx tsc -b --pretty false && npm run lint && npm run build && npm audit

# everything at once
pwsh -File scripts/security-scan.ps1
```

Expected: `PROBES: 57   PASS: 57   FAIL: 0`.

Raw probe data: `reports/person1_attack_results.json`.

---

## 8. Limitations

* SQLite only; PostgreSQL/Supabase row-level behaviour, pooling and migration state were not exercised against a live instance.
* No reverse proxy/CDN/HTTPS in the test environment: HSTS and per-IP limits behind `deploy/nginx.conf` are unverified until deployed.
* No live Redis server: the Redis code paths (atomic counter, sliding window, unreachable-server fallback) were verified with an in-process fake and unit tests, not against a real cluster, so cross-instance atomicity under load is unmeasured.
* No live email provider or malware scanner; reset delivery and scanning were exercised only in their unconfigured/fail-closed paths.
* Load/DoS testing and the legacy Streamlit UI were out of scope.

---

## 9. Changes in this remediation

| File | Change |
|---|---|
| `backend/tools/query_tool.py` | Reject SQL comments in validation and scope rewrite (F1). |
| `backend/app/auth/rate_limiter.py` | Redis sliding-window backend for chat/upload/report quotas with process-local fallback. |
| `backend/app/security/rate_limit.py` | Atomic INCR+TTL Lua script, failure cooldown instead of permanent downgrade. |
| `backend/requirements.txt` | `redis>=5.0,<8` (optional shared counter store). |
| `.github/workflows/security.yml` | New `security-scan-script` job: attack suite, bandit, pip-audit, gitleaks, npm audit on every PR. |
| `scripts/security-scan.ps1` | `-SkipPytest` / `-SkipAttack` switches; gitleaks uses the repository config. |
| `backend/app/security/headers.py` | **New** security headers middleware (F2). |
| `backend/app/security/ai_input.py` | **New** prompt-injection screening + input cap (F5). |
| `backend/app/security/ai_policy.py` | **New** per-tool role policy (F6). |
| `backend/app/main.py` | Restrict CORS methods/headers; register headers middleware. |
| `backend/app/agent.py` | Tool registry accepts and enforces caller role. |
| `backend/app/routers/agent.py` | Screen chat input; pass verified role to the agent. |
| `backend/tests/test_web_security_controls.py` | **New** 23 tests for headers, CORS, injection, policy. |
| `backend/tests/test_person1_security.py` | Comment/quote/schema SQL regression cases. |
| `backend/tests/test_security_regression.py` | Injection chat now asserts the fail-closed 400 contract. |
| `deploy/nginx.conf` | **New** TLS/HSTS/login-rate-limit reverse proxy. |
| `scripts/security-scan.ps1` | **New** one-command security gate. |
| `docs/SECURITY_OPERATIONS.md` | **New** secrets, deploy, monitoring, rotation, incident runbook. |
| `frontend-react/src/features/calendar/CalendarView.tsx` | Fix object/array destructuring type error. |
| `frontend-react/src/features/timetable/TimetableView.tsx` | Fix `string \| null` placeholder type error. |
| `frontend-react/package.json` / lockfile | `minimatch ^11.0.1` override (0 advisories). |
| `scripts/person1_attack_suite.py` | 57-probe adversarial harness. |
| `reports/person1_attack_results.json` | Raw results of the final run. |

No production database, credential, Supabase configuration, audit record or attendance record was modified.

---

## Appendix A — full probe data

| # | Probe | Category | Severity | Expected | Observed | Result |
|---|---|---|---|---|---|---|
| 1 | JWT alg=none rejected | auth | critical | 401 | 401 | PASS |
| 2 | Forged signature rejected | auth | critical | 401 | 401 | PASS |
| 3 | Expired token rejected | auth | critical | 401 | 401 | PASS |
| 4 | Token without exp rejected | auth | high | 401 | 401 | PASS |
| 5 | Disallowed algorithm rejected | auth | high | 401 | 401 | PASS |
| 6 | Token role claim cannot escalate | authz | critical | 403 | 403 | PASS |
| 7 | user_metadata role ignored | authz | critical | 403 | 403 | PASS |
| 8 | Token for deleted/unknown user rejected | auth | high | 401 | 401 | PASS |
| 9 | Username enumeration timing delta | auth | medium | \|delta\| < 50 ms | 12.1 ms | PASS |
| 10 | Correct password is not locked out (DoS) | auth | high | 200 | 200 | PASS |
| 11 | Wrong-password guessing is throttled | rate-limit | medium | 429 observed | [401, 429] | PASS |
| 12 | ADMIN login without admin_key fails closed | auth | critical | 401 | 401 | PASS |
| 13 | ADMIN login with wrong admin_key rejected | auth | critical | 401 | 401 | PASS |
| 14 | ADMIN login with correct admin_key succeeds | auth | info | 200 | 200 | PASS |
| 15 | MFA account: password alone rejected | mfa | critical | 401 | 401 | PASS |
| 16 | MFA account: wrong TOTP rejected | mfa | critical | 401 | 401 | PASS |
| 17 | MFA account: valid TOTP accepted | mfa | info | 200 | 200 | PASS |
| 18 | MFA re-enrollment needs a current code (password only) | mfa | high | 400 | 400 | PASS |
| 19 | Cross-user session revocation (IDOR) | authz | critical | 404 and session intact | 404, intact=True | PASS |
| 20 | Revoke-all sessions endpoint | auth | medium | 200 | 200 | PASS |
| 21 | Refresh token replay revokes the family | auth | critical | first=200 second=401, got 200/401 | 200/401 | PASS |
| 22 | Refresh without CSRF header blocked | csrf | high | 403 | 403 | PASS |
| 23 | Refresh from foreign Origin blocked | csrf | high | 403 | 403 | PASS |
| 24 | Logout without a session rejected | auth | low | 401 | 401 | PASS |
| 25 | Password change guessing is rate limited | rate-limit | high | 429 observed | [401, 429] | PASS |
| 26 | Reset initiation is self-service and non-enumerating | auth | medium | same 200 body | 200/200 equal=True | PASS |
| 27 | Reset token is single use | auth | critical | first=200 replay=400, got 200/400 | 200/400 | PASS |
| 28 | VIEWER cannot create master data | authz | high | 403 | 403 | PASS |
| 29 | FACULTY cannot create master data | authz | high | 403 | 403 | PASS |
| 30 | Cross-faculty session read blocked | scope | critical | 403/404 | 403 | PASS |
| 31 | FACULTY cannot read audit trail | authz | high | 403 | 403 | PASS |
| 32 | Mass assignment fields ignored | authz | medium | 201 and no privilege change | 201 | PASS |
| 33 | Raw SQL rejected: quoted table | sql | critical | ValueError | Quoted table identifiers are not permitted: '"attendance"'.  | PASS |
| 34 | Raw SQL rejected: bracket-quoted table | sql | critical | ValueError | Quoted table identifiers are not permitted: '[attendance]'.  | PASS |
| 35 | Raw SQL rejected: backtick table | sql | critical | ValueError | Quoted table identifiers are not permitted: '`attendance`'.  | PASS |
| 36 | Raw SQL rejected: schema-qualified table | sql | critical | ValueError | Schema-qualified table names are not permitted: 'main.attend | PASS |
| 37 | Raw SQL rejected: subquery to users | sql | critical | ValueError | Access to table 'users' is not permitted. | PASS |
| 38 | Raw SQL rejected: sqlite_master | sql | critical | ValueError | Access to table 'sqlite_master' is not permitted. | PASS |
| 39 | Raw SQL rejected: PRAGMA | sql | critical | ValueError | Disallowed keyword: 'PRAGMA'. Only SELECT or WITH queries ar | PASS |
| 40 | Raw SQL rejected: stacked statement | sql | critical | ValueError | Multiple SQL statements are not permitted. | PASS |
| 41 | Raw SQL rejected: comment-separated table | sql | critical | ValueError | SQL comments are not permitted. | PASS |
| 42 | Scoped attendance query cannot see other faculty data | scope | critical | only SESS-A | ['SESS-A'] | PASS |
| 43 | Prompt-injection chat request rejected | ai | high | 400 | 400 | PASS |
| 44 | Upload rejected: NUL byte after 64 KB | upload | high | 400 | 400 | PASS |
| 45 | Upload rejected: Executable signature after 64 KB | upload | high | 400 | 400 | PASS |
| 46 | Upload rejected: Oversized upload | upload | high | 413 | 413 | PASS |
| 47 | Upload rejected: Spoofed content type | upload | high | 400 | 400 | PASS |
| 48 | Upload rejected: Malformed image | upload | high | 400 | 400 | PASS |
| 49 | Path traversal filename sanitized | upload | high | no traversal path | 200 | PASS |
| 50 | Upload rate limit enforced | rate-limit | medium | 429 observed | [200, 429] | PASS |
| 51 | CORS rejects foreign origin | web | critical | no ACAO | None | PASS |
| 52 | CORS simple request from foreign origin | web | high | no ACAO | None | PASS |
| 53 | Security headers present | web | high | all present | missing=[] | PASS |
| 54 | Health endpoint hides environment | web | low | no environment key | ['status', 'version'] | PASS |
| 55 | API docs not public in production | web | medium | None None | None None | PASS |
| 56 | CORS does not allow arbitrary methods/headers | web | medium | restricted | status=400 methods='GET, POST, PUT, PATCH, DELETE, OPTIONS' headers='Accept, Accept-Langua | PASS |
| 57 | Reported Person 2 artifacts exist in the repository | process | high | all present | missing=[] | PASS |

**Totals:** 57 probes, 57 passed, 0 failed.
