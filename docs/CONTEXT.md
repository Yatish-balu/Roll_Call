# RollCall AI System Context
backend/app/main.py: FastAPI entrypoint, lifespan checks, CORS, standard error handlers, route mounts.
backend/app/auth: JWT issuance/verification, password hashing, RBAC dependencies, in-memory rate limiter.
backend/app/db: Dual SQLite/PostgreSQL engine, SQLAlchemy ORM models, migrations, CRUD access layer.
backend/app/routers: REST endpoints for auth, me, admin, sessions, attendance, analytics, reports, agent.
backend/tools: Deterministic code tools (validate_tool, read_csv_tool, read_photo_tool, summary_tool, query_tool, export_tool).
frontend-react: Vite React SPA client with Dashboard, Attendance, Timetable, Defaulters, Reports, AI Chat.
data/attendance.db: SQLite local database with verified baseline schema.

## Database Tables & Schema
users(user_id PK, name, role, password_hash, is_active, created_at)
teacher_subjects(id PK, teacher_id FK, subject_code, subject_name, semester, branch)
audit_log(log_id PK, event, actor_id, session_id, usn, old_value, new_value, reason, at_utc)
login_attempts(id PK, user_id, at_utc, success)
pending_edits(pending_id PK, user_id, session_id, usn, old_status, new_status, created_at_utc, expires_at_utc, used)
students(usn PK, name, branch)
rooms(room_id PK, name)
sessions(session_id PK, date, subject_code, subject_name, teacher_id, created_at_utc, editable, locked)
attendance(id PK, session_id FK, usn FK, room_id FK, status, source, confidence)

## API Endpoints
POST /api/auth/login, GET /api/auth/me, POST /api/auth/logout, POST /api/auth/refresh
GET /api/me/subjects, GET /api/meta/config
GET /api/admin/users, GET/POST/DELETE /api/admin/teacher-subjects, GET /api/admin/overview, GET /api/admin/audit-log
POST/GET /api/sessions, GET /api/sessions/{id}/attendance, PUT /api/sessions/{id}/attendance/{usn}
GET /api/analytics/sessions/{id}/summary, GET /api/analytics/overview, GET /api/defaulters
GET /api/reports/export/excel, GET /api/reports/export/pdf, GET /api/admin/defaulters.pdf
POST /api/agent/chat, POST /api/agent/process-file, POST /api/agent/confirm, GET /api/agent/status
GET /api/students, GET /api/students/{usn}/ledger, GET /api/rooms, GET /api/calendar

## Agent Tools & Inputs
validate_tool(records, master_usns, master_rooms) -> ValidationResult
read_csv_tool(file_path, default_room, default_branch) -> CSVExtractionResult
read_photo_tool(image_path, min_confidence) -> PhotoExtractionResult
summary_tool(records, symbol_map) -> SummaryReport
query_tool(query_type, session_id, room_id, branch, usn, status, sql, user_context) -> QueryResult
export_tool(summary_report, output_path, format) -> ExportResult

## Project Rules
Read docs/CONTEXT.md first; do not scan the repo. Touch only the files I name. New routes go in app/routers/<name>.py and are included in app/api.py with one include line. All role, lock and permission checks are Python code; the LLM never decides permissions. User id and role come only from the verified token, never from the request body, query, or chat text. All database calls live in app/db.py. Streamlit is frozen: no new Streamlit screens. Errors use the standard body in docs/API_CONTRACT.md. Never log or return passwords, tokens or keys.

