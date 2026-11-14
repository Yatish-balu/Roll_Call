# RollCall AI — API Contract

All endpoints use the standard error body:

```json
{ "error": { "code": "CODE", "message": "Human-readable message" } }
```

Codes: `UNAUTHENTICATED` 401, `FORBIDDEN` 403, `LOCKED` 403, `NOT_FOUND` 404,
`VALIDATION` 422, `QUALITY_REJECTED` 422, `RATE_LIMITED` 429.

All times are ISO-8601 UTC ending in `Z`. Percent is a number with 1 decimal.
Band is the string `green`, `yellow` or `red`.

Every session object has: `session_id`, `date`, `subject_code`, `subject_name`,
`teacher_id`, `created_at_utc`, `editable` (bool), `editable_until_utc` (or null),
`locked` (bool).

No field is ever renamed or removed after this contract; only added.

---

## Authentication

### POST /api/auth/login
Body: `{ "user_id": "...", "password": "...", "admin_key": "..." }` (admin_key optional, required for admin)
Response 200: `{ "token": "...", "role": "...", "name": "...", "subject_codes": [...], "expires_at_utc": "..." }`
Errors: 401 (wrong password / unknown user), 429 (rate limited)

### GET /api/auth/me
Requires: authentication
Response: `{ "user_id": "...", "email": "...", "role": "...", "claims": {...} }`

---

## Configuration

### GET /api/meta/config
Requires: authentication
Response:
```json
{
  "edit_lock_hours": 24,
  "unlimited_attendance_editing": true,
  "admin_override_allowed": true,
  "defaulter_threshold_percent": 75.0,
  "defaulter_required_percent": 75.0,
  "attendance_bands": {
    "green_above_percent": 85.0,
    "yellow_from_percent": 70.0,
    "labels": { "green": "green", "yellow": "yellow", "red": "red" }
  },
  "upload_limits": {
    "image_max_bytes": 10485760,
    "csv_max_bytes": 5242880
  },
  "chat_confirm_expiry_minutes": 5,
  "access_token_ttl_minutes": 480,
  "subject_codes": ["CN", "OS", "ML", "DB"]
}
```

---

## Teacher-Subject Mapping

### GET /api/me/subjects
Requires: authentication (teacher or admin)
Response: `{ "user_id": "...", "role": "...", "subject_codes": ["CN", "OS"] }`

### GET /api/admin/users?role=teacher
Requires: ADMIN
Response: list of users

### GET /api/admin/teacher-subjects
Requires: ADMIN
Response: `{ "items": [...], "total": N }`

### POST /api/admin/teacher-subjects
Requires: ADMIN
Body: `{ "user_id": "...", "subject_code": "..." }`
Response 201: `{ "success": true, "message": "..." }`

### DELETE /api/admin/teacher-subjects
Requires: ADMIN
Query: `?user_id=...&subject_code=...`
Response 200: `{ "success": true, "message": "..." }`

---

## Sessions

### POST /api/sessions
Requires: authentication (FACULTY or ADMIN)
Body: `{ "subject_code": "CN", "date_str": "2026-11-14", "session_id": "..." }`
- FACULTY: subject_code must be one of their assigned subjects; teacher_id from token.
- ADMIN: can assign any teacher_id.
Response 201: `{ "session_id": "...", "subject": "...", "date": "...", "message": "..." }`
Errors: 403 (unassigned subject), 409 (duplicate)

### GET /api/sessions?from=&to=&teacher_id=
Requires: authentication
Response:
```json
{
  "items": [
    {
      "session_id": "...",
      "date": "2026-11-14",
      "subject_code": "CN",
      "subject_name": "Computer Networks",
      "teacher_id": "...",
      "created_at_utc": "...",
      "editable": true,
      "editable_until_utc": "...",
      "locked": false
    }
  ],
  "total": N,
  "limit": 50,
  "offset": 0
}
```

### GET /api/sessions/{id}/attendance
Requires: authentication
Response: session object plus rows `[{ usn, name, status, source, confidence }]`

### PUT /api/sessions/{id}/attendance/{usn}
Body: `{ "status": "PRESENT", "reason": "..." }`
Requires: authentication; teacher owns session; admin override reason for sessions > 24h
Response: `{ "session_id": "...", "usn": "...", "old_status": "...", "new_status": "...", "event": "ATTENDANCE_EDIT" }`
Errors: 403 (LOCKED / FORBIDDEN), 404, 422

---

## Chat-Based Attendance Edits (N7)

### Tool: update_attendance_tool
LLM-facing. Resolves intent from natural language, stores pending edit.
Response: `{ "status": "proposed", "needs_confirmation": true, "confirmation_id": "...", "confirmation_request": { "question": "..." } }`

### POST /api/agent/attendance/propose
Body: `{ "query": "...", "session_id": "...", "usn": "...", "new_status": "PRESENT", "reason": "..." }`
Response: proposal with confirmation_id and confirmation_request.

### POST /api/agent/attendance/confirm
Body: `{ "confirmation_id": "...", "reason": "...", "request_id": "..." }`
Response: `{ "success": true, "status": "confirmed", "old_status": "...", "new_status": "..." }`

### POST /api/chat/confirm
Query: `?pending_id=...&decision=yes` (or `no`)
Body: optional `{ "reason": "..." }`
Response: `{ "success": true, "confirmed": true/false, "decision": "yes"/"no", "message": "..." }`

---

## Defaulters

### GET /api/defaulters?subject=&branch=&semester=&threshold=
Requires: authentication
Response:
```json
{
  "status": "success",
  "threshold": 75.0,
  "required_percent": 75.0,
  "defaulter_count": 2,
  "total_students": 5,
  "students": [
    {
      "usn": "1DS22CS001",
      "name": "Alice Smith",
      "branch": "CSE",
      "attended": 12,
      "conducted": 20,
      "percent": 60.0,
      "classes_needed": 12,
      "is_defaulter": true
    }
  ]
}
```

### GET /api/admin/defaulters.pdf?subject=&branch=&semester=&threshold=
Requires: ADMIN
Response: PDF file (application/pdf)

---

## Student Lookup & Ledger

### GET /api/students/lookup?q=
Requires: authentication
Response: `{ "results": [{ "usn": "...", "name": "...", "branch": "..." }], "total": N }`

### GET /api/students/{usn}/ledger
Requires: authentication
Response:
```json
{
  "usn": "...",
  "name": "...",
  "branch": "...",
  "total_classes": 10,
  "present": 7,
  "absent": 3,
  "attendance_percentage": "70.0%",
  "percent": 70.0,
  "band": "yellow",
  "ledger": [
    { "session_id": "...", "date": "...", "subject": "...", "subject_code": "...", "status": "...", "source": "...", "confidence": 1.0 }
  ]
}
```

---

## Calendar

### GET /api/calendar?month=YYYY-MM&subject=
Requires: authentication
Response:
```json
{
  "month": "2026-11",
  "subject": "CN",
  "days": [
    { "date": "2026-11-13", "sessions": 1, "present": 4, "absent": 1, "percent": 80.0, "band": "yellow" }
  ]
}
```

### GET /api/calendar/day?date=YYYY-MM-DD&subject=
Requires: authentication
Response: `{ "date": "...", "subject": "...", "sessions": [...] }`

### GET /api/calendar/export.ics
Requires: ADMIN
Response: .ics file (text/calendar)

---

## Admin Read Endpoints

### GET /api/admin/overview
Requires: ADMIN
Response: present/absent/percent per branch and per room.

### GET /api/admin/faculty-uploads
Requires: ADMIN
Response: per-teacher last upload time, sessions in last 7 days, sessions this semester.

### GET /api/admin/audit-log?event=&actor=&from=&to=&page=&page_size=
Requires: ADMIN
Response: `{ "items": [...], "total": N, "limit": 50, "offset": 0 }`
Read-only: no UPDATE or DELETE on audit_log.
