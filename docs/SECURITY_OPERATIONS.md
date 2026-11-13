# RollCall AI — Unified Security Operations Runbook

**Owners:** Person 1 (Backend, Auth & Data Security) & Person 2 (Frontend, Infrastructure & AI Security)

Operational guidance for running RollCall AI securely in production. It documents required environment secrets, edge and reverse proxy configurations, HTTP headers, AI defense-in-depth, operational checklists, backup/disaster recovery, and incident response.

Application-layer controls are covered by `backend/tests/test_person1_security.py`, `backend/tests/test_person2_security.py`, and `backend/tests/test_security_regression.py`. Black-box probe suites live in `scripts/person1_attack_suite.py` and `scripts/person2_attack_suite.py`.

---

## 1. Required Configuration & Secrets

Secrets must come from the platform secret store (e.g. AWS Secrets Manager, Vault, or secure container secrets), **never** from a committed file.

| Variable | Required | Purpose / Failure Mode |
|---|---|---|
| `APP_ENV=production` | Yes | Enables production hardening: docs disabled, HSTS, scanner fail-closed, secret validation. |
| `JWT_SECRET` | Yes | ≥32 chars, not the development fallback. Startup refuses otherwise. |
| `ADMIN_KEY` | Yes | Second factor for ADMIN password login; login fails closed without it. |
| `MFA_ENCRYPTION_KEY` | Yes | URL-safe base64 32-byte key for AES-GCM TOTP secrets. MFA login fails closed if unset. |
| `ALLOWED_ORIGINS` | Yes | Comma-separated exact origins (e.g. `https://rollcall.example.edu`). Wildcards are rejected. |
| `DATABASE_URL` / `SUPABASE_*` | Yes | Production database. SQLite is for local development only. |
| `SMTP_HOST` (+ credentials) | Recommended | Password reset delivery. Without it the startup log records a deployment blocker. |
| `MALWARE_SCAN_COMMAND` | Recommended | ClamAV-compatible scanner. Production uploads are **rejected** when no scanner is configured. |
| `AUDIT_CHAIN_HMAC_SECRET` | Recommended | HMAC key for the append-only audit chain. |
| `TRUST_PROXY_HEADERS=true` | Behind trusted proxy only | Trust `X-Forwarded-For` / `X-Forwarded-Proto`. Never enable on a directly exposed server. |
| `REDIS_URL` | Recommended for >1 instance | `redis://[:password]@host:6379/0`. Shared counters for account lockout, login/refresh/reset quotas and chat limiter. Without it, counters live in the application DB. |
| `SEC_*_LIMIT` / `SEC_*_WINDOW` | Optional | Per-scope rate-limit overrides (see `app/security/rate_limit.py`). |

---

## 2. HTTPS & Edge Security Headers

### Where the Controls Live

| Control | Primary Location | Application Fallback |
|---|---|---|
| HTTPS / TLS | Reverse proxy or CDN | `uvicorn` TLS flags |
| HSTS | Reverse proxy/CDN | `backend/app/security/headers.py` |
| CSP | Reverse proxy/CDN | `backend/app/security/headers.py` |
| X-Content-Type-Options | Reverse proxy/CDN | `backend/app/security/headers.py` |
| Referrer-Policy | Reverse proxy/CDN | `backend/app/security/headers.py` |
| Permissions-Policy | Reverse proxy/CDN | `backend/app/security/headers.py` |
| Clickjacking | Reverse proxy/CDN | `X-Frame-Options: DENY` + `frame-ancestors 'none'` |
| CORS | FastAPI (`backend/app/main.py`) | Handled via exact-origin validation |

Reference configurations:
* `deploy/nginx/rollcall.conf`
* `deploy/Caddyfile`

### Required Production Behavior

1. TLS 1.2+ only (prefer TLS 1.3), valid certificate, HTTP redirected to HTTPS.
2. `Strict-Transport-Security: max-age=31536000; includeSubDomains` (add `preload` only after the domain is ready).
3. CSP tuned to the frontend origin. Scripts restricted to same-origin.
4. `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`, `X-Frame-Options: DENY`.
5. Edge upload limit set to `10 MB` to match FastAPI's max upload limit.

---

## 3. CORS Configuration

Configured by `backend/app/main.py`:
* `ALLOWED_ORIGINS`: exact `scheme://host[:port]` origins, comma-separated. Wildcards, path prefixes, queries, and fragments are rejected.
* `ALLOWED_METHODS`: explicit method allowlist; `OPTIONS` is always permitted.
* `ALLOWED_HEADERS`: explicit allowlist. `X-Requested-With` and `X-RollCall-CSRF` are automatically appended for CSRF verification on cookie-based refresh/logout.
* In production, setting `SECURITY_HEADERS_ENABLED=false` causes startup to fail.

---

## 4. AI Security & Defense-in-Depth

### Tool Permissions
Enforced by `ToolRegistry.execute` in `backend/app/security/ai_policy.py`:
* `query_tool`: minimum role `VIEWER`.
* `read_csv_tool`, `read_photo_tool`, `validate_tool`, `summary_tool`, `export_tool`: minimum role `FACULTY`.
* Opaque sentinel `TRUSTED_INTERNAL` is required for internal scripts; the legacy Streamlit UI refuses to run when `APP_ENV=production`.
* Roles originate from cryptographically verified JWT tokens, never model prompts.

### Prompt Injection Screening & Obfuscation Decoding
* `backend/app/security/ai_input.py` sanitizes untrusted input using Unicode NFKC normalization, removing zero-width characters and stripping casing.
* Multi-layer decoders detect base64, hexadecimal, ROT13, HTML entities, and Unicode escapes before evaluation.
* Chat inputs exceeding 4000 characters are rejected at the Pydantic schema boundary.
* Uploaded files are inspected in overlapping chunks to ensure injections are never missed across window boundaries.

### Multi-Tenant Data Isolation
* All database queries run through `resolve_data_scope(db, current_user)`.
* Raw SQL queries are validated and rewritten: quoted and schema-qualified table references are rejected (`fail closed`), and table names are substituted with row-level sub-selects scoped to the user's assigned classes/sessions.

---

## 5. Backups and Disaster Recovery

### Automated Backup Execution
```powershell
# The script refuses to run without an encryption passphrase and 7-Zip.
$env:BACKUP_ENCRYPTION_PASSWORD = "<strong-passphrase>"
pwsh ./deploy/backup/backup.ps1 -RetentionDays 30
```
* **SQLite:** Consistent `sqlite3 .backup` snapshot with SHA-256 integrity verification.
* **PostgreSQL / Supabase:** `pg_dump` execution when `DATABASE_URL_SYNC` is defined.
* **Encryption:** Every archive is 7-Zip AES-256 encrypted with encrypted headers
  (`-mhe=on`); an unencrypted archive is never written.
* Daily automated backups stored with versioning and encryption at rest.

### Quarterly Restore Drill
1. Copy the latest archive to an isolated staging environment.
2. Verify checksum integrity (`sha256sum -c`).
3. Restore database file or execute schema migration.
4. Execute smoke test suite (login, attendance query, AI chat, session creation).
5. Target recovery objectives: RPO ≤ 24h, RTO ≤ 4h.

---

## 6. Dependency Scanning & Local Verification

Run the full security scan locally:
```powershell
pwsh ./scripts/security-scan.ps1
```

Individual checks:
```bash
# Backend security analysis
python -m pip_audit -r backend/requirements.txt
python -m bandit -r backend/app backend/tools -ll
gitleaks detect --source . --config .gitleaks.toml --redact --no-banner

# Frontend dependency security
cd frontend-react
npm audit --audit-level=high
npm run build
npm run lint
```

---

## 7. Joint Deployment Checklist

- [ ] `APP_ENV=production`, strong `JWT_SECRET`, `ADMIN_KEY`, `MFA_ENCRYPTION_KEY` configured in secret manager.
- [ ] `ALLOWED_ORIGINS` configured strictly with production HTTPS origins (no wildcards).
- [ ] Reverse proxy terminates TLS with HTTP -> HTTPS redirection.
- [ ] Security headers (HSTS, CSP, X-Frame-Options, nosniff, Permissions-Policy) active.
- [ ] `TRUST_PROXY_HEADERS=true` enabled only if reverse proxy is sole ingress.
- [ ] `REDIS_URL` configured for multi-instance deployments for shared rate limits and account lockout.
- [ ] Email provider configured; end-to-end password reset flow verified.
- [ ] ClamAV malware scanner configured; clean and infected samples verified.
- [ ] Full automated test suite passing (`pytest tests -q`).
- [ ] Full security scan script passing (`scripts/security-scan.ps1`).
- [ ] Legacy Streamlit UI disabled in production.
- [ ] Database backup and restore drill documented and validated.
