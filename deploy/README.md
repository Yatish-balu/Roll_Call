# Deployment assets (Person 2)

These files are deployment examples, not automatically applied. Choose the edge
that matches your hosting provider and keep the policies aligned with
`backend/app/security/headers.py`.

| Path | Purpose |
| --- | --- |
| `nginx/rollcall.conf` | Nginx HTTPS termination, security headers, static frontend and API proxy |
| `Caddyfile` | Caddy alternative with automatic HTTPS |
| `backup/backup.ps1` | Consistent SQLite/PostgreSQL backup + checksum + retention |
| `monitoring/promtail-config.yml` | Ship the JSONL security event log to Loki |
| `monitoring/README.md` | Alert thresholds and privacy guidance |

## Suggested deployment shape

```
Internet
  -> CDN / WAF (optional, TLS + headers + rate limits)
  -> Nginx or Caddy (TLS termination, HSTS, CSP, static React build)
       -> FastAPI/uvicorn on 127.0.0.1:8000
       -> SQLite file or Supabase/PostgreSQL
```

## Required environment (production)

```env
APP_ENV=production
ALLOWED_ORIGINS=https://app.example.com
ALLOWED_METHODS=GET,POST,PUT,PATCH,DELETE,OPTIONS
ALLOWED_HEADERS=Accept,Authorization,Content-Type,Origin,X-Request-ID,X-CSRF-Token,X-Requested-With,X-RollCall-CSRF
SECURITY_HEADERS_ENABLED=true
HSTS_MAX_AGE=31536000
HSTS_INCLUDE_SUBDOMAINS=true
JWT_SECRET=<at least 32 random characters, stored in a secret manager>
SECURITY_EVENT_LOG_FILE=/var/log/rollcall/security-events.jsonl
```

Use a secret manager or the platform's environment/secret store. Never commit
real secrets to `.env`, the repository or these examples.

The legacy Streamlit UI uses trusted internal tool access and has no React
authentication flow. It refuses to run unless `APP_ENV=development` and
`LEGACY_STREAMLIT_ENABLED=true`; keep it disabled and do not expose it beyond
local development.

## Apply

1. Build the frontend: `cd frontend-react && npm ci && npm run build`.
2. Copy `frontend-react/dist/*` to `/var/www/rollcall/frontend/`.
3. Start the API: `cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000`.
4. Install the proxy config and reload Nginx/Caddy.
5. Run `pwsh ./scripts/security-scan.ps1`, then the verification commands in
   `docs/SECURITY_OPERATIONS.md`.

## Health checks

* `GET /health` -> `{"status":"healthy", ...}`
* `GET /` -> welcome message
* TLS/header check: `curl -sI https://app.example.com/health`
