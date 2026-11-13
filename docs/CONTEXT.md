# RollCall AI — Access Control & RBAC Context (RC-RBAC-002)

## Role Scope Policy

RollCall AI enforces strict server-side Role-Based Access Control (RBAC) across FastAPI routes (`backend/app/deps.py`, `backend/app/auth/dependencies.py`), session/data scoping (`backend/app/auth/session_scope.py`), and the AI SQL/analytics query layer (`backend/tools/query_tool.py`).

### 1. Administrator (`admin` / `Role.ADMIN`) — College-Wide Unrestricted Scope
- **Global Scope:** Users with `role = 'admin'` operate with **unrestricted college-wide access** across all departments, branches, rooms, students, attendance records, audit logs, and subjects.
- **No `dept_id` Restriction:** Even if an administrator profile carries an optional `dept_id`, admin queries **never** inject a `dept_id` or `subject_code` `WHERE` filter unless explicitly requested via query parameters on filtering endpoints (e.g., `?branch=CSE`, `?dept_id=...`).
- **Deferred HOD Columns:** Schema columns intended for post-freeze department-level leadership (`departments.head_of_dept_id` and `department_staff`) are intentionally unused in query/auth logic and must not filter admin visibility.
- **Legacy & Unowned Sessions:** Admins retain read and override access across all sessions (including legacy/unowned sessions). Attendance overrides beyond the edit window remain audited with actor identity and reason.

### 2. Teacher / Faculty (`teacher` / `Role.FACULTY`) — Strictly Mapped Scope
- **Mapped Assignment Scope:** Faculty accounts are scoped strictly to:
  1. Sessions they directly own (`sessions.teacher_id == user_id`),
  2. Unowned/legacy sessions (`teacher_id IS NULL` or `'legacy'`) where they are recorded as `coordinator_faculty_id`, or whose normalized `subject_code` matches an exact row mapped to them in `faculty_subjects` / `teacher_subjects`.
- **Query Tool Enforcement:** When `UserContext.role == 'teacher'` (or `Role.FACULTY`), `tools/query_tool.py` restricts table scans and SQL rewrites strictly to visible sessions and mapped `subject_codes`.

### 3. Viewer (`viewer` / `Role.VIEWER`)
- Read-only access limited strictly to scoped sessions/data matching mapped assignments; denied mutating endpoints and admin routes (`403 Forbidden`).

## Key Modules
- `backend/app/deps.py`: Exports `UserContext`, `require_role(...)`, `require_login`, and `get_user_context`. `require_role('admin')` grants unrestricted college-wide access.
- `backend/app/auth/session_scope.py`: Defines `SessionScope`, `DataScope`, `resolve_session_scope`, and `resolve_data_scope`.
- `backend/tools/query_tool.py`: Injects no `dept_id` or `subject_code` `WHERE` clause when `UserContext.role == 'admin'` (`unrestricted=True`), while enforcing strict mapped `subject_code` filtering for `teacher` / `faculty`.

