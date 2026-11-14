# RollCall AI — Backend Context

One line per file, every DB table with columns, every API endpoint, every agent tool.
Max 60 lines.

## Core Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI app, router registration, startup (tool registration, profile table) |
| `app/config.py` | Named constants: lock hours, bands, defaulter threshold, upload limits, TTLs |
| `app/policy.py` | N5: `is_editable()`, `editable_until()`, `lock_hours()` — pure lock functions |
| `app/health.py` | N12: `health_band(percent)` — green >85, yellow 70–85, red <70 |
| `app/errors.py` | N3: `ApiError`, `error_response()`, standard `{error:{code,message}}` |
| `app/deps.py` | N3: `require_login`, `require_role(role)` convenience deps |
| `app/dependencies.py` | `get_db()` session dependency |

## Database Tables

| Table | Columns |
|-------|---------|
| `users` | user_id, name, email, role, password_hash, is_active, created_at |
| `faculty_subjects` | id, user_id, subject_code, subject_name, semester, branch |
| `sessions` | session_id, date, subject, subject_code, created_at, teacher_id, coordinator_faculty_id, lifecycle_status |
| `attendance` | attendance_id, session_id, usn, room_id, status, source, confidence, recorded_at |
| `audit_log` | log_id, actor_id, actor_role, action, session_id, usn, entity_type, entity_id, old_value, new_value, reason, timestamp, chain_id, prev_hash, row_hash |
| `login_attempts` | id, user_id, ip_address, success, timestamp |
| `pending_edits` | edit_id, user_id, session_id, usn, old_status, new_status, created_at, expires_at, consumed |

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/auth/login` | none | JWT login with rate limiting |
| GET | `/api/auth/me` | auth | Current user profile |
| GET | `/api/meta/config` | auth | Server configuration (bands, locks, limits) |
| GET | `/api/me/subjects` | auth | Teacher's assigned subjects |
| GET/POST/DELETE | `/api/admin/teacher-subjects` | admin | Teacher-subject mapping CRUD |
| GET | `/api/admin/users?role=teacher` | admin | List teachers |
| POST | `/api/sessions` | auth | Create session (subject from mapping) |
| GET | `/api/sessions` | auth | List sessions with lock fields |
| GET | `/api/sessions/{id}/attendance` | auth | Session attendance rows |
| PUT | `/api/sessions/{id}/attendance/{usn}` | auth | Atomic attendance edit + audit |
| POST | `/api/agent/attendance/propose` | auth | N7: propose chat attendance edit |
| POST | `/api/agent/attendance/confirm` | auth | N7: confirm pending edit |
| POST | `/api/chat/confirm` | auth | N7: chat confirm (pending_id + yes/no) |
| GET | `/api/defaulters` | auth | N10: defaulter analysis |
| GET | `/api/admin/defaulters.pdf` | admin | N11: defaulter PDF report |
| GET | `/api/students/lookup?q=` | auth | N12: student search |
| GET | `/api/students/{usn}/ledger` | auth | N12: student ledger with band |
| GET | `/api/calendar?month=` | auth | N13: calendar month data |
| GET | `/api/calendar/day?date=` | auth | N13: calendar day detail |
| GET | `/api/calendar/export.ics` | admin | iCalendar export |
| GET | `/api/admin/overview` | admin | Admin dashboard overview |
| GET | `/api/admin/faculty-uploads` | admin | Per-teacher upload stats |
| GET | `/api/admin/audit-log` | admin | Read-only audit log |

## Agent Tools

| Tool | Purpose | RBAC |
|------|---------|------|
| `summarize_attendance` | Attendance statistics | FACULTY/ADMIN/COORDINATOR/STUDENT/VIEWER |
| `get_class_schedule` | Scheduled sessions | FACULTY/ADMIN/COORDINATOR/STUDENT/VIEWER |
| `find_vacant_classrooms` | Room availability | FACULTY/ADMIN/COORDINATOR/STUDENT |
| `create_attendance_session` | Create session | FACULTY/ADMIN |
| `update_user_profile` | Update profile | FACULTY/ADMIN/COORDINATOR/STUDENT |
| `query_student_attendance_record` | Student history | FACULTY/ADMIN/COORDINATOR |
| `get_pending_unreviewed_sessions` | Pending sessions | FACULTY/ADMIN/COORDINATOR |
| `read_csv_tool` | Parse CSV | FACULTY/ADMIN |
| `read_photo_tool` | OCR photo | FACULTY/ADMIN (quality gate first) |
| `validate_tool` | Validate records | FACULTY/ADMIN |
| `summary_tool` | Summarize attendance | FACULTY/ADMIN |
| `query_tool` | Read-only SQL | FACULTY/ADMIN/COORDINATOR |
| `export_tool` | Excel/PDF export | FACULTY/ADMIN |
| `single_attendance_correction` | Single edit with undo | FACULTY/ADMIN |
| `bulk_attendance_proposal` | Bulk edit proposal | FACULTY/ADMIN (confirm required) |
| `get_my_profile` | My profile | FACULTY/ADMIN/COORDINATOR |
| `get_defaulters_analysis` | Defaulter stats | FACULTY/ADMIN |
| `create_session` | Multi-room session | FACULTY/ADMIN |
| `get_my_timetable` | My timetable | FACULTY/ADMIN/COORDINATOR |
| `get_day_schedule` | Day schedule | FACULTY/ADMIN/COORDINATOR |
| `update_attendance_tool` | N7: chat edit proposal | FACULTY/ADMIN |

## Security Rules

- Role comes only from verified JWT + database, never from request body.
- `audit_log` append-only: DB triggers reject UPDATE and DELETE.
- No passwords, tokens, or keys logged or returned.
- CORS: origins from `ALLOWED_ORIGINS`, no wildcards.
- Security headers on every response (CSP, X-Frame-Options, etc.).
- Rate limiting: 5 failed logins per user_id per 10 min → 429.
