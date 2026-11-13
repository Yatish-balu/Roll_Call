# RollCall AI — Specification

Backend implementation specification for the attendance management system.

## Sections

1. [Authentication & Authorization](#1-authentication--authorization)
2. [Teacher-Subject Mapping](#2-teacher-subject-mapping)
3. [Session Management](#3-session-management)
4. [Attendance Editing & Lock Policy](#4-attendance-editing--lock-policy)
5. [Chat-Based Attendance Edits](#5-chat-based-attendance-edits)
6. [Admin Endpoints](#6-admin-endpoints)
7. [Quality Gate](#7-quality-gate)
8. [Defaulter Analysis](#8-defaulter-analysis)
9. [Student Lookup & Ledger](#9-student-lookup--ledger)
10. [Calendar](#10-calendar)
11. [Security](#11-security)

---

## 1. Authentication & Authorization

- Role comes only from the verified JWT token and the database `users` table.
- Roles: `ADMIN`, `FACULTY`, `VIEWER`. ADMIN inherits all capabilities.
- Every `/api` route except `/api/health` and `/api/auth/login` requires authentication.
- Rate limiting: 5 failed login attempts per user_id in 10 minutes → 429.
- JWT: HS256, 8-hour expiry, `JWT_SECRET` from `.env` (must be ≥32 chars).

---

## 2. Teacher-Subject Mapping

- `GET /api/me/subjects` — teacher's assigned subject codes.
- Admin: `GET /api/admin/users?role=teacher`, `GET/POST/DELETE /api/admin/teacher-subjects`.
- Every mapping change writes an `audit_log` row.

---

## 3. Session Management

- `POST /api/sessions` — subject_code comes from teacher's mapping; unassigned → 403.
- `GET /api/sessions?from=&to=&teacher_id=` — each item includes `editable`, `editable_until_utc`, `locked`.
- Teacher sees own sessions only; admin sees all.

---

## 4. Attendance Editing & Lock Policy

- 24-hour lock: `now - created_at ≤ 24h` is editable for teachers; admin always editable.
- `app/policy.py`: `is_editable()`, `editable_until()`, `lock_hours()`.
- `PUT /api/sessions/{id}/attendance/{usn}` — atomic write + audit in one transaction.
- Admin editing a session older than 24h must provide a reason (`ADMIN_OVERRIDE_EVENT`).
- `audit_log` is append-only: database triggers reject UPDATE and DELETE.

---

## 5. Chat-Based Attendance Edits

- Tool `update_attendance_tool` prepares a pending edit (never modifies attendance).
- `POST /api/agent/attendance/propose` — Step A: store pending edit (5-min expiry, single-use).
- `POST /api/agent/attendance/confirm` — Step B: apply the pending edit.
- `POST /api/chat/confirm` — chat confirmation (pending_id + yes/no decision).
- The LLM cannot confirm by itself — confirmation is a separate server step.

---

## 6. Admin Endpoints

- `GET /api/admin/overview` — present/absent/percent per branch and room.
- `GET /api/admin/faculty-uploads` — per-teacher upload stats.
- `GET /api/admin/audit-log?event=&actor=&from=&to=&page=` — read-only, paginated.
- `GET /api/admin/defaulters.pdf` — defaulter report PDF.

---

## 7. Quality Gate

- Photo uploads checked for blur (Laplacian variance) and brightness (mean pixel).
- Thresholds: sharpness ≥ 100, brightness 60–200.
- Failed → 422 `QUALITY_REJECTED` with reasons and measured values.
- Vision API is NOT called on failed images.

---

## 8. Defaulter Analysis

- `GET /api/defaulters?subject=&branch=&semester=&threshold=`
- Per student: usn, name, branch, attended, conducted, percent, classes_needed, is_defaulter.
- Defaulter = strictly below threshold (75.0 is NOT a defaulter).
- Formula t=75: `classes_needed = max(0, 3*conducted - 4*attended)`.
- `GET /api/admin/defaulters.pdf` — admin PDF report.

---

## 9. Student Lookup & Ledger

- `GET /api/students/lookup?q=` — partial USN or name, max 20 results.
- `GET /api/students/{usn}/ledger` — attendance history with percent and colour band.
- Colour bands: green >85, yellow 70–85 inclusive, red <70 (class health, not eligibility).

---

## 10. Calendar

- `GET /api/calendar?month=YYYY-MM&subject=` — per-day data with band.
- `GET /api/calendar/day?date=YYYY-MM-DD&subject=` — day's sessions.
- `GET /api/calendar/export.ics` — admin iCalendar export.

---

## 11. Security

- All permissions decided by Python code or database — never by the LLM.
- React only shows what the API sends.
- Errors use standard body: `{"error": {"code": "CODE", "message": "..."}}`.
- Codes: UNAUTHENTICATED 401, FORBIDDEN 403, LOCKED 403, NOT_FOUND 404, VALIDATION 422, QUALITY_REJECTED 422, RATE_LIMITED 429.
- No passwords, tokens, or keys logged or returned.
