# Faculty security audit — remediation record

Response to `Faculty_Security_Audit_Assessment.pdf` (3-page assessment of the
supplied audit narrative for `test_faculty`, `faculty_ai`, `faculty_cn`).

The source report was not independently available; items below are split into
**fixed in code**, **requires an operator action**, and **not tested**.

## Fixed in code

| Priority | Finding | Change | Evidence |
| --- | --- | --- | --- |
| P0 | Password-variant authentication (V-01) | Login compares the submitted password verbatim with bcrypt; no trimming/rewrite/normalisation is performed. | `backend/tests/test_password_exactness.py` — exact password succeeds, leading/trailing space, removed punctuation, punctuation→space and case changes all get 401. |
| P1 | Committed development JWT secret (V-03) | `DEV_FALLBACK_SECRET` is now generated per process with `secrets.token_urlsafe(48)`; production still rejects it and requires `JWT_SECRET`. | `backend/app/auth/jwt.py`, `test_person1_security.py`. |
| P1 | Hardcoded seed passwords | Both seed scripts now require `SEED_*` / `SEED_PASSWORD_*` environment variables in every environment. No credential defaults remain in source. | `backend/scripts/seed_users.py`, `backend/scripts/seed_demo.py`, `.env.example`. |
| P2 | Personalised responses cacheability | All `/api` and `/api/v1` responses get `Cache-Control: no-store` and `Pragma: no-cache`. | `backend/app/security/headers.py`, `test_web_security_controls.py`. |
| P2 | Duplicate `/api` and `/api/v1` exposure | Formally documented as the Playbook/Streamlit compatibility surface, controlled by `ENABLE_LEGACY_API_PREFIX` (default on). Both prefixes use the same routers and controls. | `backend/app/main.py`, `.env.example`. |
| P2 | Migration/model drift after the OTP migration | The `otp_codes` Core table is declared on shared model metadata, including its unique constraint and expiry index. | `backend/app/db/models.py`, `test_n1_n4_regressions.py::test_fresh_migration_chain_matches_sqlalchemy_models`. |
| P3 | Anonymous `/models` endpoint | Remains rate-limited (`rate_limit_models`) on all four aliases. | `backend/app/main.py`. |

## Requires an operator action (cannot be fixed in this repository)

1. **V-02 `faculty_ai` credential mismatch** — correct the seed/provisioning
   value in the identity store (the intended password must hash to the stored
   value), then confirm login with that *exact* credential. Do not rely on
   password-variant acceptance to mask the defect. No `faculty_ai` seed value
   exists in this repository; it must be corrected where the account is
   provisioned. Verify the exact result with
   `backend/scripts/verify_credential.py` (never prints the password/hash).
2. **Secret rotation** — any seed password or development JWT secret that may
   have been used in shared, staging or production environments must be
   rotated. If values were committed to Git history, assess history cleanup
   under the repository's retention policy; deleting them from HEAD is not
   sufficient. Runbook: `docs/SECURITY_OPERATIONS.md` §8. Existing users' hashes
   can be updated with `backend/scripts/rotate_password.py` (never logs the
   secret and revokes all sessions); verified by
   `backend/tests/test_secret_rotation.py`.
3. **Supabase RLS** — review SELECT/INSERT/UPDATE/DELETE policies directly in
   the Supabase project for the relevant tables and faculty ownership
   boundaries. API-layer authorisation tests are **not** equivalent. Read-only
   inventory SQL and an evidence checklist are in
   `docs/supabase-rls-review.md`.

## Not tested (keep marked NOT TESTED, not PASSED)

- Supabase RLS (no direct SQL/project access available in this environment).
- TLS terminator / edge HSTS (no TLS endpoint available locally).
- AI-provider output safety and SMTP delivery (required environment
  configuration absent).
- Admin-role behaviour was excluded from the supplied faculty audit by
  instruction.

## Verification performed after remediation

- Exact/mutated password regression tests: pass.
- OTP password-reset flow tests: pass.
- Header regression tests: pass.
- Full backend suite: **953 passed, 0 failed**. Earlier runs exposed a
  migration/model drift failure, a dev-secret literal reference, a date-dependent
  exam test and a too-tight brightness test; all were corrected before the
  final green run.
- Front-end: `tsc -b` and `vite build` clean; tab navigation no longer
  refetches all data because the shell is persistent and GETs are cached.
