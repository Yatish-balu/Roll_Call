# RollCall AI — Security Operations Runbook

Operational guidance for running RollCall AI in production. It documents the
secrets the service needs, the deployment checklist, monitoring, rotation and
incident response, and the controls that are enforced in code.

The application-layer controls referenced here are covered by
`backend/tests/test_web_security_controls.py` and `backend/tests/test_person1_security.py`,
and the black-box probes live in `scripts/person1_attack_suite.py`.

---

## 1. Required configuration

Secrets must come from the platform secret store (not from a committed file).

| Variable | Required | Purpose / failure mode |
|---|---|---|
| `APP_ENV=production` | yes | Enables production hardening: docs disabled, HSTS, scanner fail-closed, secret validation. |
| `JWT_SECRET` | yes | ≥32 chars, not the development fallback. Startup refuses otherwise. |
| `ADMIN_KEY` | yes | Second factor for ADMIN password login; login fails closed without it. |
| `MFA_ENCRYPTION_KEY` | yes | URL-safe base64 32-byte key for AES-GCM TOTP secrets. MFA login fails closed if unset. |
| `ALLOWED_ORIGINS` | yes | Comma-separated exact origins (e.g. `https://rollcall.example.edu`). Wildcards are rejected. |
| `DATABASE_URL` / `SUPABASE_*` | yes | Production database. SQLite is for local development only. |
| `SMTP_HOST` (+ credentials) | recommended | Password reset delivery. Without it the startup log records a deployment blocker. |
| `MALWARE_SCAN_COMMAND` | recommended | ClamAV-compatible scanner. Production uploads are **rejected** when no scanner is configured. |
| `AUDIT_CHAIN_HMAC_SECRET` | recommended | HMAC key for the append-only audit chain. |
| `TRUST_PROXY_HEADERS=true` | only behind a trusted proxy | Trust `X-Forwarded-For` / `X-Forwarded-Proto`. Never enable on a directly exposed server. |
| `REDIS_URL` | recommended for >1 instance | `redis://[:password]@host:6379/0`. Shared counters for account lockout, login/refresh/reset quotas and the chat/upload/report limiter. Without it the counters live in the application database (shared, but one row lock per attempt). |
| `SEC_*_LIMIT` / `SEC_*_WINDOW` | optional | Per-scope rate-limit overrides (see `app/security/rate_limit.py`). |

---

## 2. Deployment checklist

1. `APP_ENV=production`, strong `JWT_SECRET`, `ADMIN_KEY`, `MFA_ENCRYPTION_KEY` set.
2. `ALLOWED_ORIGINS` contains only the real frontend origin(s) over HTTPS.
3. Reverse proxy terminates TLS and serves `deploy/nginx.conf` (HSTS, header
   duplication, login rate limit, `/docs` blocked at the edge).
4. `TRUST_PROXY_HEADERS=true` only when the proxy is the sole ingress.
5. `REDIS_URL` configured when more than one application instance runs, so
   lockouts and endpoint quotas are shared (`backend_mode()` reports `redis`).
   Locally: `docker compose up -d redis` (see `docker-compose.yml`), then set
   `REDIS_URL=redis://127.0.0.1:6379/0`. Production Redis must be authenticated
   and private; the compose service is a localhost-only development convenience.
6. Email provider configured; request one password reset end-to-end.
7. Malware scanner configured; upload a known-clean and a known-bad sample.
8. `python -m pytest tests -q` green on the release commit.
9. `pwsh -File scripts/security-scan.ps1` green (Bandit, pip-audit, gitleaks,
   npm audit, tests, attack suite). The `security` workflow runs it on every PR.
10. The legacy Streamlit UI (`backend/app/ui.py`, port 8501) is **not** exposed.
11. Database backups verified by an actual restore, not just a snapshot job.

---

## 3. Controls enforced in the application

| Control | Where |
|---|---|
| Browser security headers (nosniff, frame-deny, referrer, permissions, CSP, HSTS over TLS) | `app/security/headers.py` |
| CORS: exact origins, explicit methods and headers | `app/main.py` |
| Prompt-injection screening + 4,000-char input cap | `app/security/ai_input.py`, `app/routers/agent.py` |
| Per-tool minimum role, deny-by-default | `app/security/ai_policy.py`, `app/agent.py` |
| SQL read-only policy, comment/quote/schema bypass rejection | `tools/query_tool.py` |
| Session-scoped data access | `app/auth/session_scope.py` |
| MFA, lockout, single-use reset tokens, refresh-token rotation | `app/routers/auth.py`, `app/security/` |
| Upload size, magic-byte, image-bomb, malware checks | `app/routers/agent.py`, `app/security/uploads.py` |
| Security event log + access-denial detection | `app/security/events.py`, `app/security/detection.py` |

---

## 4. Monitoring and alerting

Watch the structured security events (`event_type` field):

* `repeated_access_denied` — credential stuffing / broken client.
* `rate_limit_triggered` — brute force or scraping.
* `prompt_injection_detected` — someone is steering the assistant. Review the
  actor and the sessions they can see.
* `upload_rejected`, `upload_scanner_unavailable` — malware attempts or a
  misconfigured deployment.
* `session_revoked`, `token_reuse_detected` — token theft.
* Audit chain verification failures (`tools/verify_audit_chain.py`) — tampering.

Alert on: any `severity=critical`, more than 10 `prompt_injection_detected` for
one actor per hour, any `token_reuse_detected`, and audit-chain mismatch.

---

## 5. Key rotation

1. **JWT_SECRET** — issue a new secret, keep the old one valid only for the
   access-token lifetime (≤1 h), then remove it. All refresh tokens must be
   revoked if the secret may have leaked.
2. **MFA_ENCRYPTION_KEY** — decrypt/re-encrypt stored TOTP secrets with a
   migration script during a maintenance window; never rotate without
   re-encrypting.
3. **ADMIN_KEY** — rotate in the secret store; sessions are password-based and
   remain valid until expiry, so revoke the admin's sessions too.
4. **Database credentials** — rotate in the provider, update the app, verify
   connectivity, then revoke the old credential.

---

## 6. Incident response

1. **Contain** — revoke the affected user's sessions (`POST /api/v1/me/sessions/revoke-all`),
   disable the account, and if credentials may be compromised rotate the relevant key.
2. **Preserve** — export the audit log and security events for the window;
   do not edit attendance or audit records in place.
3. **Assess** — determine which sessions/students the actor could see using the
   data-scope policy, and which tools the actor's role could reach.
4. **Eradicate** — patch the defect, add a regression test in
   `backend/tests/test_person1_security.py` or `test_web_security_controls.py`,
   and extend `scripts/person1_attack_suite.py`.
5. **Recover** — restore from a verified backup only if data integrity is in
   question; re-run the security scan before redeploying.
6. **Report** — record timeline, impact, root cause and the regression test that
   prevents recurrence.

---

## 7. Known limitations / residual risk

* **SQLite development database** — production must use PostgreSQL/Supabase;
  SQLite has no row-level security and weak concurrency.
* **Rate limiting without `REDIS_URL` is database-backed.** Counters are shared
  across workers on the same database, but each attempt takes a row lock and a
  cross-region deployment should set `REDIS_URL`. If Redis is configured but
  unreachable, the limiter degrades to the database (security scopes) or the
  process-local window (chat/upload/report quotas) and logs the degraded mode;
  it never disables itself.
* **Development docs** — `/docs`, `/redoc`, `/openapi.json` are intentionally
  available in development and disabled when `APP_ENV=production`.
* **Malware scanning** depends on `MALWARE_SCAN_COMMAND`; production fails
  closed (uploads rejected) rather than accepting unscanned files.
* **Email delivery** must be configured or self-service reset is unavailable.
* **The AI model is not a security boundary** — scope, SQL policy and tool
  policy are enforced in code; prompt-injection screening is defence in depth.
* **HSTS** requires HTTPS end-to-end; on plain HTTP it is intentionally absent.
