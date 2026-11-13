# RollCall AI - Architectural Decisions
# Saved from RollCall AI Expansion - Full Prompt Playbook (Group 7)

These close the gaps in the spec so the system behavior is well-defined and consistent across backend and frontend.

| # | Question | Decision (Recommended) |
|---|---|---|
| **D1** | **Who decides role and lock?** | Python only. Role from the verified token and the users table. Lock computed at edit time: now minus created_at (UTC). The LLM only calls tools. |
| **D2** | **Is is_locked stored?** | Optional column, never trusted. Truth = created_at. No background job. |
| **D3** | **Anti-spoofing claim** | Do NOT claim it. Call it Quality Gate (sharpness and brightness) in report and demo. |
| **D4** | **Google Calendar** | Export .ics file (importable). Real OAuth sync only if everything else is finished. |
| **D5** | **Colour bands** | Green above 85, yellow 70 to 85 inclusive, red below 70. Bands are class health, not eligibility. One function: `app/health.py`. |
| **D6** | **Audit log** | Append-only table with database triggers rejecting UPDATE and DELETE, plus a test. |
| **D7** | **Admin login** | user ID + password + ADMIN_KEY from `.env`. Admin accounts only from `scripts/seed_users.py`, never sign-up. |
| **D8** | **Proxy selector** | Dropdown of the teacher's assigned subjects (a teacher may have several). |
| **D9** | **Defaulter percent** | Per subject for faculty. Admin PDF also has one overall line per student. Defaulter = strictly below 75.0%. |
| **D10** | **Database** | Stay on SQLite (all calls behind `app/db.py`). Do not move to Supabase now. |
| **D11** | **Legacy sessions (NEW)** | Old sessions get `created_at = their date at 00:00 UTC`, `teacher_id = 'legacy'`, `subject_code` from old subject text or `'UNKNOWN'`. Only admin can edit them. |
| **D12** | **Admin override (NEW)** | Admin edit of a session older than 24 h needs a reason text. Logged as `ADMIN_OVERRIDE_EVENT`. |
| **D13** | **Chat edits (NEW)** | Two steps. Step 1 prepares and stores a pending edit server-side (bound to user, 5 min expiry, single use). Step 2 confirm (Yes) re-runs every check. |
| **D14** | **Time display (NEW)** | API sends UTC with Z. React shows local time (IST) using one helper function. |
| **D15** | **Error body (NEW)** | `{error: {code, message}}` with codes `UNAUTHENTICATED` 401, `FORBIDDEN` 403, `LOCKED` 403, `NOT_FOUND` 404, `VALIDATION` 422, `QUALITY_REJECTED` 422, `RATE_LIMITED` 429. |


D16 (RC-RBAC-002): Admin access is strictly college-wide and unrestricted across all departments, branches, rooms, and subjects (`users.role = 'admin'` / `Role.ADMIN` applies zero `dept_id` or `subject_code` filters, even if a `dept_id` profile field is present). Teacher/faculty access (`Role.FACULTY`) is scoped strictly to their owned/coordinated sessions and mapped rows in `faculty_subjects` / `teacher_subjects`. Department-level leadership schema columns (`departments.head_of_dept_id` and `department_staff`) remain unused and deferred for post-freeze HOD features so they never filter admin queries.
