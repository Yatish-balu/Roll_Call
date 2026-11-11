# Person 2 — Security Fixes and Verification Report

Scope: **Frontend + Infrastructure + AI Security**
Repository: `Roll_Call`
Date: 2026-11-11

This report documents the code, configuration, scans and tests added to close
the Person 2 work division. Items that require operator/hosting access (DNS,
certificates, CDN account, log platform, backup storage) are marked as
**operator action** and have runbooks/examples in the repo.

---

## 1. Phase 1 — HTTP security

| Control | Status | Where |
| --- | --- | --- |
| HTTPS / TLS | Example + docs | `deploy/nginx/rollcall.conf`, `deploy/Caddyfile`, `docs/SECURITY_OPERATIONS.md` |
| HSTS | Implemented (app + edge) | `backend/app/security/headers.py`, edge configs |
| Content-Security-Policy | Implemented (strict API, relaxed docs) | `backend/app/security/headers.py` |
| X-Content-Type-Options | Implemented | middleware + edge |
| Referrer-Policy | Implemented | middleware + edge |
| Permissions-Policy | Implemented | middleware + edge |
| Clickjacking protection | Implemented (`X-Frame-Options` + `frame-ancestors`) | middleware + edge |
| Controls at reverse proxy/CDN | Example configs | `deploy/` |

The middleware is pure ASGI, so headers are applied to every response,
including CORS preflights and error responses. Existing proxy values are kept
(`setdefault`) so a stronger edge policy is never weakened.

## 2. Phase 2 — CORS

Implemented in `backend/app/main.py`:

* exact-origin allowlist (`ALLOWED_ORIGINS`);
* wildcard, credentials, paths, queries, fragments and non-http(s) origins are
  rejected;
* default ports are canonicalised (`:443`/`:80` removed);
* explicit method allowlist (`ALLOWED_METHODS`, `OPTIONS` always added);
* explicit request-header allowlist (`ALLOWED_HEADERS`);
* required `X-Requested-With` and `X-RollCall-CSRF` headers remain allowed even
  when `ALLOWED_HEADERS` is customized;
* `X-Request-ID` exposed for correlation;
* `allow_credentials=True` only with explicit origins (never `*`).

Tests cover allowed origin, unknown origin, method/header allowlists, wildcard
fallback and normalisation.

## 3. Phase 3 — AI security

### Tool authorization

Added `backend/app/security/ai_policy.py` with the server-side matrix:

| Tool | Minimum role |
| --- | --- |
| `query_tool` | VIEWER |
| `read_csv_tool` / `read_photo_tool` / `validate_tool` / `summary_tool` / `export_tool` | FACULTY |

`ToolRegistry.execute` (in `backend/app/agent.py`) always enforces the matrix
before a handler runs. Missing roles default to VIEWER; explicitly trusted
internal jobs must pass the `TRUSTED_INTERNAL` sentinel. The HTTP routers supply
the role from verified authentication context. The legacy Streamlit UI is
refused in production.

### Prompt injection

Added `backend/app/security/ai_input.py`:

* detects instruction override, system-prompt/secret exfiltration, role
  escalation, authorization bypass, jailbreak and boundary spoofing;
* the chat endpoint rejects matches with HTTP 400 and logs
  `prompt_injection_blocked` (with a bounded excerpt);
* chat input is capped at 4000 characters.

### Malicious uploaded files

Complete uploaded CSV/text content (up to the existing upload-size limit) is
inspected in bounded windows for embedded instruction payloads and logged as
`embedded_instruction_detected`. Unicode formatting controls are normalized;
common Base64 and hexadecimal representations are checked. Content remains
data; the pipeline and tool sequence are unchanged. Existing upload hardening
(size, magic bytes, extension/MIME consistency, image dimensions, malware hook)
remains in force.

### Cross-user isolation

Every AI read uses `resolve_data_scope(db, current_user)`, and `query_tool`
applies the same session/student predicate as the REST API. Existing
end-to-end coverage in `backend/tests/test_c1_c2_scope_and_audit_api.py`
verifies that out-of-scope sessions, raw SQL and student lists return no data.

## 3a. Joint-audit remediation (Person 2 findings)

The joint audit (`reports/JOINT_SECURITY_AUDIT_REPORT.md`) raised two genuine
Person 2 findings, one low-severity hardening item, and three observations.
All six checklist items are closed in the repository:

| Item | Status | Evidence |
| --- | --- | --- |
| CORS/CSRF integration (P1) | Fixed | `X-Requested-With` and `X-RollCall-CSRF` are in `DEFAULT_ALLOWED_HEADERS` and are re-appended even when `ALLOWED_HEADERS` is customized. End-to-end browser-equivalent test: `test_login_refresh_logout_browser_cors_preflights`. |
| Prompt-injection bypasses (P2) | Fixed | NFKC normalisation, invisible/format-character stripping, lowercasing, Base64/hex decoding, expanded vocabulary and a multilingual rule. 10/10 audit payloads blocked; regressions in `test_prompt_injection_obfuscation_regressions`. |
| Missing `actor_role` (P3) | Fixed | Missing/invalid roles default to `VIEWER` (fail closed). `TRUSTED_INTERNAL` is an opaque sentinel used only by internal jobs. Covered by `test_registry_without_actor_role_defaults_to_viewer` and `test_registry_allows_explicit_trusted_internal_sentinel`. |
| Upload inspection limited to 64 KB | Fixed | The upload endpoint inspects the complete bounded payload; `find_prompt_injection` scans overlapping windows so a payload after 64 KB or across a boundary is still found. Regression: `test_prompt_inspection_covers_payload_past_first_64kb_and_window`; manual check found a payload at char 128,079. |
| Headers disableable in production | Fixed | `SECURITY_HEADERS_ENABLED=false` raises `RuntimeError` during production startup, and the middleware force-enables headers whenever `APP_ENV=production`. |
| Joint regression suite | Passed | `python -m pytest tests -q` -> 698 passed, 2 skipped. Re-run `scripts/person2_attack_suite.py`: all Person 2 probes (headers, CORS incl. C9, AI incl. A3/A4) `SECURE`; remaining failures are Person 1 findings (MFA, SQL scope, session IDOR, lockout, `/health`, OpenAPI). |

Changing the role default required internal-only callers to state their trust
explicitly: `backend/app/ui.py` (which now refuses to start when
`APP_ENV=production`), `backend/demo_agent.py`,
`backend/scripts/evaluate_agent.py`, and the internal agent tests pass
`TRUSTED_INTERNAL`. No HTTP path can reach that sentinel.

---

## 4. Phase 4 — Dependency and infrastructure

### Dependency scans

| Scan | Result |
| --- | --- |
| `npm audit` (before) | 7 moderate (dev-only `typescript-eslint` → `minimatch`) |
| `npm audit` (after) | **0 vulnerabilities** |
| `pip-audit -r backend/requirements.txt` | **No known vulnerabilities** |
| `pip check` | Passed |
| Frontend `tsc -b`, ESLint, Vite build | Passed |
| Backend tests | **698 passed, 2 skipped** |

Remediation: added a targeted npm override
`@typescript-eslint/typescript-estree → minimatch ^11.0.8` (lockfile updated),
then verified build/lint.

CI `.github/workflows/security.yml` now fails the frontend job on high/critical
npm findings (previously it only warned). Python `pip-audit`, `bandit`,
`gitleaks` and `pip check` remain enforced.

### Reverse proxy / CDN

Added `deploy/nginx/rollcall.conf` (TLS, HSTS, CSP, headers, static frontend,
API proxy, upload limits, rate limits) and `deploy/Caddyfile` (automatic HTTPS).

### Backups / disaster recovery

Added `deploy/backup/backup.ps1`:

* consistent SQLite snapshot (`sqlite3 .backup`) with copy fallback;
* `pg_dump` for PostgreSQL/Supabase when configured;
* SHA-256 checksum per archive;
* retention pruning.

Restore drill and RPO/RTO guidance: `docs/SECURITY_OPERATIONS.md`.

### Monitoring / alerting

Added `deploy/monitoring/promtail-config.yml` and `deploy/monitoring/README.md`
with alert thresholds for auth failures, access-denied spikes, prompt-injection
and malicious-upload events, rate limits, 5xx, certificate expiry and backup
failure. Set `SECURITY_EVENT_LOG_FILE` to ship the existing JSONL security
events.

---

## 5. Files added / changed

### Added

* `backend/app/security/headers.py`
* `backend/app/security/ai_policy.py`
* `backend/app/security/ai_input.py`
* `backend/tests/test_person2_security.py` (56 tests)
* `deploy/nginx/rollcall.conf`
* `deploy/Caddyfile`
* `deploy/backup/backup.ps1`
* `deploy/monitoring/promtail-config.yml`
* `deploy/monitoring/README.md`
* `deploy/README.md`
* `docs/SECURITY_OPERATIONS.md`
* `scripts/security-scan.ps1`

### Changed

* `backend/app/main.py` — hardened CORS + security headers middleware
* `backend/app/agent.py` — tool authorization enforcement
* `backend/app/routers/agent.py` — actor role, prompt-injection guard, embedded
  instruction detection
* `backend/app/schemas/agent.py` — chat query max length
* `.env.example`, `backend/.env.example` — CORS/header settings
* `.github/workflows/security.yml` — npm audit now blocking
* `frontend-react/package.json` / `package-lock.json` — minimatch override
* `backend/pytest.ini` — removed an invalid warning filter that broke pytest on
  the installed Starlette version
* `backend/tests/test_person1_security.py`,
  `backend/tests/test_security_regression.py` — isolated JWT tests from the
  operator `.env`, and updated the prompt-injection expectation to accept the
  new explicit rejection
* `backend/tests/test_auth_sessions.py` — browser-equivalent CORS preflight
  coverage for login -> refresh -> logout
* `backend/app/ui.py`, `backend/demo_agent.py`,
  `backend/scripts/evaluate_agent.py` — explicit `TRUSTED_INTERNAL` for
  non-HTTP execution; the Streamlit UI refuses to start in production
* `backend/tests/test_agent.py`, `backend/tests/test_hard_prompt7.py`,
  `backend/tests/test_ui.py` — internal agent tests use `TRUSTED_INTERNAL`
* `scripts/person2_attack_suite.py` — A3 probe now verifies fail-closed
  defaults and explicit internal execution
* `.gitignore` — ignore test temp directory debris
* `README.md` — security/operations section and updated test count

---

## 6. Verification commands

```powershell
# Backend
cd backend
python -m pytest tests -q

# Frontend
cd ../frontend-react
npm audit --audit-level=high
npm run build
npm run lint

# Combined
pwsh ./scripts/security-scan.ps1
```

Verified results at the time of writing:

* backend: `698 passed, 2 skipped`
* Person 2 security module: `46 passed`
* frontend: `0 vulnerabilities`, build and lint clean
* Python: no known vulnerabilities from `requirements.txt`

---

## 7. Operator actions still required

These cannot be completed from the repository alone and must be done in the
deployment environment:

1. **DNS + TLS certificate** for the production domain; enforce HTTP → HTTPS.
2. **Install the edge config** (Nginx/Caddy) and verify the headers with
   `curl -sI https://<domain>/health`.
3. **Set production environment** (`APP_ENV=production`,
   `ALLOWED_ORIGINS=https://<frontend>`, strong `JWT_SECRET`, etc.).
4. **Point `SECURITY_EVENT_LOG_FILE` at a shipped log path** and route alerts.
5. **Configure off-host, encrypted backup storage** and run a restore drill.
6. **Manual adversarial testing with Person 1**: each person attempts to break
   the other's controls, then run the full regression suite.
7. **Do not expose the legacy Streamlit UI** (`backend/app/ui.py`) in
   production; it is a local/development interface without the React auth flow.
