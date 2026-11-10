# RollCall AI Expansion - Full Prompt Playbook (Group 7)
## Project Reference & Roadmap

### Project Overview
- **Freeze Date:** end of 19 Nov
- **Deadline:** 25 Nov
- **Approach:** Option C: API contract first. Old features in React, new screens built against fake data. New backend built in waves.
- **Branches:** `feature/rbac-backend` (Backend) / `feature/react-ui` (Frontend).

### Golden Rule
> **Every permission, lock and number is decided by Python code or the database.**
> The LLM only picks tools and writes sentences. React only shows what the API sends.
> If a prompt result breaks this rule, reject it.

### Core Rules
1. **One prompt = one fresh chat.** Long chats burn tokens.
2. **Review with `git diff --stat` first**, then open only the files that matter.
3. **Never paste keys.** `.env` stays in `.gitignore`. Only `.env.example` (names, no values) is committed.
4. **All role, lock and permission checks are Python code;** the LLM never decides permissions. User ID and role come only from the verified token, never from the request body, query, or chat text.
5. **Errors use standard body** `{error: {code, message}}`.

### Roadmap Prompts Summary

#### Wave 1: Database, Login, Protected Routes, Mapping
- **N1**: Database changes (`users`, `teacher_subjects`, `audit_log`, `login_attempts`, `pending_edits`, `sessions` columns, triggers). **DONE** (migrations `0002_rbac_tables`, `0003_auth_sessions`; append-only audit triggers verified by tests)
- **N2**: Login with tokens, rate limit (bcrypt, JWT valid 15 min with rotation, 7-day session family, refresh-cookie rotation with reuse detection, 5 failed attempts in 10m -> 429). **DONE**
- **N3**: Protect every route, scope the chat reader, error format (require_login, require_role, UserContext for query_tool). **DONE** (all routers behind `get_current_user` / `require_roles`; D15 error body via global handlers)
- **N4**: Teacher-subject mapping, session create, meta config (`/api/me/subjects`, `/api/admin/teacher-subjects`, `/api/meta/config`). **DONE** (faculty session-create scoped to assigned subject codes; teacher_id bound to token; audit rows for `SESSION_CREATE` / `TEACHER_SUBJECT_ASSIGN`; dev DB migrated to head + users seeded)

#### Wave 2: Lock, Safe Edits, Chat Edits
- **N5**: 24-hour lock policy (pure function `is_editable(session_created_at_utc, role, now_utc)`).
- **N6**: One safe write function plus audit log (`update_attendance()`, atomic transaction with `audit_log`).
- **N6b**: Session list and attendance read with lock fields (`editable`, `editable_until_utc`, `locked`).
- **N7**: `update_attendance_tool` for chat with server-side confirmation (`prepare_edit` -> pending_id -> confirm).

#### Wave 3: Admin, Quality Gate, Defaulters, Lookup
- **N8**: Admin overview, faculty uploads, audit log viewer (`/api/admin/overview`, `/api/admin/faculty-uploads`, `/api/admin/audit-log`).
- **N9**: Blur and lighting quality gate (sharpness via Laplacian variance, brightness via mean pixel value -> 422 QUALITY_REJECTED).
- **N10**: Defaulter engine and endpoint (`defaulters()`, `classes_needed = max(0, 3*conducted - 4*attended)`).
- **N11**: Defaulter PDF for the notice board (ReportLab export, admin only, audit logged).
- **N12**: Student lookup and ledger (`/api/students/lookup`, `/api/students/{usn}/ledger`, color bands).

#### Wave 4: Calendar, Hardening, Demo Data, Joining Support
- **N13**: Calendar month data and day detail (`/api/calendar?month=YYYY-MM`, `/api/calendar/day`).
- **N14**: Calendar .ics export (optional, admin only).
- **N15**: Security hardening (upload limits: images 10MB, CSV 5MB, formula escaping, read-only SQLite for query_tool).
- **N16**: Demo and test seed data (`seed_demo.py`).
- **N17**: Dev connection: CORS, proxy, run script.
- **N18**: Contract test script (`test_contract.py`).
- **N19**: Integration and security run.

### Viva Questions & Answers
- **Why does the LLM not check permissions?**
  It can be tricked by prompt injection or conversational text. Python code checks the cryptographically verified token claims and DB role.
- **How do you stop a teacher editing an old session?**
  Lock is computed from `created_at` in UTC inside the single write function `update_attendance()`.
- **Can the chat confirm an edit by itself?**
  No. The tool only prepares; confirmation is a separate server step bound to the user ID, single-use, with 5-minute expiry.
- **What is in the audit log and can an admin delete it?**
  Actor ID, event, session ID, USN, old value, new value, reason, UTC timestamp. SQLite triggers reject UPDATE and DELETE operations.
- **How is the number of classes needed worked out?**
  $x = \lceil(0.75 \times \text{conducted} - \text{attended}) / 0.25\rceil = 3 \times \text{conducted} - 4 \times \text{attended}$ for 75%.
- **Why does React not calculate percentages or locks?**
  Single source of truth: Python backend and the database.
- **Why is it called a quality gate and not anti-spoofing?**
  It checks image clarity (sharpness and brightness) only; it cannot detect a counterfeit attendance sheet.

