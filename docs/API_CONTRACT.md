# RollCall AI API Contract (New Endpoints)

All error responses strictly follow the standard shape:
```json
{
  "error": {
    "code": "UNAUTHENTICATED | FORBIDDEN | LOCKED | NOT_FOUND | VALIDATION | QUALITY_REJECTED | RATE_LIMITED",
    "message": "Human readable message"
  }
}
```

All timestamps are ISO-8601 UTC ending in `Z`. Percentages are numbers with 1 decimal place. Health bands are strings `"green"`, `"yellow"`, or `"red"`.

---

## 1. Authentication & Configuration

### `POST /api/auth/login`
- **Caller**: Public
- **Request**:
```json
{
  "user_id": "faculty_ds",
  "password": "FacultyPass_DIST_2026!",
  "admin_key": null
}
```
- **Response**:
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "role": "FACULTY",
  "name": "Dr. Smith",
  "subject_codes": ["DIST-SYS", "DB-SYS"],
  "expires_at_utc": "2026-11-11T06:00:00Z"
}
```
- **Errors**: `UNAUTHENTICATED` (401), `RATE_LIMITED` (429)

### `GET /api/auth/me`
- **Caller**: Teacher / Admin
- **Response**:
```json
{
  "user_id": "faculty_ds",
  "email": "faculty.ds@rollcall.internal",
  "role": "FACULTY",
  "name": "Dr. Smith",
  "subject_codes": ["DIST-SYS", "DB-SYS"]
}
```
- **Errors**: `UNAUTHENTICATED` (401)

### `GET /api/meta/config`
- **Caller**: Teacher / Admin
- **Response**:
```json
{
  "bands": {
    "green_min": 85.0,
    "yellow_min": 70.0
  },
  "lock_hours": 24,
  "default_threshold": 75.0
}
```
- **Errors**: `UNAUTHENTICATED` (401)

### `GET /api/me/subjects`
- **Caller**: Teacher only
- **Response**:
```json
[
  {
    "subject_code": "DIST-SYS",
    "subject_name": "Distributed Systems",
    "semester": 5,
    "branch": "CSE"
  }
]
```
- **Errors**: `UNAUTHENTICATED` (401), `FORBIDDEN` (403)

---

## 2. Administration & Teacher Mapping

### `GET /api/admin/users?role=teacher`
- **Caller**: Admin only
- **Response**:
```json
[
  {
    "user_id": "faculty_ds",
    "name": "Dr. Smith",
    "email": "faculty.ds@rollcall.internal",
    "role": "FACULTY",
    "is_active": true
  }
]
```
- **Errors**: `UNAUTHENTICATED` (401), `FORBIDDEN` (403)

### `GET /api/admin/teacher-subjects`
- **Caller**: Admin only
- **Response**:
```json
[
  {
    "id": 1,
    "teacher_id": "faculty_ds",
    "teacher_name": "Dr. Smith",
    "subject_code": "DIST-SYS",
    "subject_name": "Distributed Systems",
    "semester": 5,
    "branch": "CSE"
  }
]
```

### `POST /api/admin/teacher-subjects`
- **Caller**: Admin only
- **Request**:
```json
{
  "teacher_id": "faculty_ds",
  "subject_code": "DBMS",
  "subject_name": "Database Management Systems",
  "semester": 5,
  "branch": "CSE"
}
```
- **Response**: `201 Created`

### `DELETE /api/admin/teacher-subjects/{id}`
- **Caller**: Admin only
- **Response**: `200 OK`

---

## 3. Sessions & Attendance Management

Every session object contains:
```json
{
  "session_id": "SESS-20261110-01",
  "date": "2026-11-10",
  "subject_code": "DIST-SYS",
  "subject_name": "Distributed Systems",
  "teacher_id": "faculty_ds",
  "created_at_utc": "2026-11-10T09:00:00Z",
  "editable": true,
  "editable_until_utc": "2026-11-11T09:00:00Z",
  "locked": false
}
```

### `POST /api/sessions`
- **Caller**: Teacher / Admin
- **Request**:
```json
{
  "session_id": "SESS-20261110-01",
  "date": "2026-11-10",
  "subject_code": "DIST-SYS",
  "room_id": "LH-101"
}
```
- **Response**: Session object above.
- **Errors**: `UNAUTHENTICATED` (401), `FORBIDDEN` (403) if subject not assigned.

### `GET /api/sessions`
- **Caller**: Teacher (returns own sessions) / Admin (returns all sessions)
- **Query Params**: `from`, `to`, `teacher_id`
- **Response**: Array of Session objects.

### `GET /api/sessions/{id}/attendance`
- **Caller**: Teacher (own session) / Admin (all)
- **Response**:
```json
{
  "session": { "session_id": "SESS-20261110-01", "locked": false, "editable": true },
  "records": [
    {
      "usn": "1MS21CS001",
      "name": "Alice Smith",
      "status": "PRESENT",
      "source": "CSV",
      "confidence": 1.0
    }
  ]
}
```

### `PUT /api/sessions/{id}/attendance/{usn}`
- **Caller**: Teacher (own session <= 24h) / Admin (any session, reason required if > 24h)
- **Request**:
```json
{
  "status": "ABSENT",
  "reason": "Administrative correction for medical leave"
}
```
- **Response**:
```json
{
  "success": true,
  "session_id": "SESS-20261110-01",
  "usn": "1MS21CS001",
  "old_status": "PRESENT",
  "new_status": "ABSENT"
}
```
- **Errors**: `LOCKED` (403), `VALIDATION` (422) if invalid status or admin override reason missing, `NOT_FOUND` (404).

---

## 4. Photo Quality Gate

When a photo fails sharpness or brightness standards:
- **Status**: `422 Unprocessable Content`
- **Response**:
```json
{
  "error": {
    "code": "QUALITY_REJECTED",
    "message": "Photo not clear enough. Please retake.",
    "details": {
      "reasons": ["Image is blurred (Laplacian variance 42.1 below threshold 100.0)"],
      "sharpness": 42.1,
      "brightness": 128.4,
      "thresholds": {
        "min_sharpness": 100.0,
        "min_brightness": 60.0,
        "max_brightness": 200.0
      }
    }
  }
}
```

---

## 5. Agent Chat & Pending Edits

### `POST /api/chat`
- **Caller**: Teacher / Admin
- **Request**:
```json
{
  "query": "Mark 1MS21CS001 as Present for DIST-SYS today"
}
```
- **Response**:
```json
{
  "reply": "Prepared change for student 1MS21CS001.",
  "tools_used": ["query_tool", "prepare_edit_tool"],
  "needs_confirmation": true,
  "pending_id": "pend_9f8e7d6c",
  "confirm_text": "Change 1MS21CS001 from Absent to Present for DIST-SYS on 2026-11-10?"
}
```

### `POST /api/chat/confirm`
- **Caller**: Teacher / Admin (owner of pending_id)
- **Request**:
```json
{
  "pending_id": "pend_9f8e7d6c",
  "decision": "yes"
}
```
- **Response**:
```json
{
  "success": true,
  "message": "Confirmed: 1MS21CS001 updated to PRESENT. Audit log entry created.",
  "session_id": "SESS-20261110-01",
  "usn": "1MS21CS001",
  "status": "PRESENT"
}
```
- **Errors**: `LOCKED` (403), `VALIDATION` (422) expired or invalid pending edit.

---

## 6. Admin Analytics, Faculty Monitoring & Audit Logs

### `GET /api/admin/overview`
- **Caller**: Admin only
- **Response**:
```json
{
  "total_records": 1240,
  "present": 1054,
  "absent": 186,
  "percentage": 85.0,
  "branch_wise": [
    { "branch": "CSE", "present": 520, "absent": 80, "percentage": 86.7 }
  ],
  "room_wise": [
    { "room_id": "LH-101", "present": 310, "absent": 40, "percentage": 88.6 }
  ]
}
```

### `GET /api/admin/faculty-uploads`
- **Caller**: Admin only
- **Response**:
```json
[
  {
    "teacher_id": "faculty_ds",
    "name": "Dr. Smith",
    "last_upload_utc": "2026-11-10T14:30:00Z",
    "sessions_last_7_days": 4,
    "sessions_this_semester": 28
  }
]
```

### `GET /api/admin/audit-log`
- **Caller**: Admin only
- **Query Params**: `event`, `actor`, `from`, `to`, `page`, `page_size`
- **Response**:
```json
{
  "total": 45,
  "page": 1,
  "page_size": 50,
  "items": [
    {
      "log_id": 1,
      "event": "ADMIN_OVERRIDE_EVENT",
      "actor_id": "admin_root",
      "session_id": "SESS-20261025-01",
      "usn": "1MS21CS001",
      "old_value": "ABSENT",
      "new_value": "PRESENT",
      "reason": "HOD sanctioned medical certificate",
      "at_utc": "2026-11-10T12:00:00Z"
    }
  ]
}
```

---

## 7. Defaulters & Ledger

### `GET /api/defaulters`
- **Caller**: Teacher (own subject only) / Admin (all)
- **Query Params**: `subject`, `branch`, `semester`, `threshold` (default 75.0)
- **Response**:
```json
[
  {
    "usn": "1MS21CS002",
    "name": "Bob Jones",
    "branch": "CSE",
    "attended": 14,
    "conducted": 20,
    "percent": 70.0,
    "classes_needed": 4,
    "band": "yellow"
  }
]
```

### `GET /api/admin/defaulters.pdf`
- **Caller**: Admin only
- **Response**: Streaming PDF binary.

### `GET /api/students/lookup?q={query}`
- **Caller**: Teacher / Admin
- **Response**:
```json
[
  { "usn": "1MS21CS001", "name": "Alice Smith", "branch": "CSE" }
]
```

### `GET /api/students/{usn}/ledger`
- **Caller**: Teacher (own subject) / Admin (all)
- **Response**:
```json
{
  "usn": "1MS21CS001",
  "name": "Alice Smith",
  "overall_percent": 92.5,
  "band": "green",
  "sessions": [
    {
      "date": "2026-11-10",
      "subject": "DIST-SYS",
      "room_id": "LH-101",
      "status": "PRESENT",
      "source": "CSV"
    }
  ]
}
```

---

## 8. Calendar & Scheduling

### `GET /api/calendar?month=YYYY-MM&subject={subject}`
- **Caller**: Teacher / Admin
- **Response**:
```json
[
  {
    "date": "2026-11-10",
    "sessions_count": 2,
    "present": 58,
    "absent": 6,
    "percent": 90.6,
    "band": "green"
  }
]
```

### `GET /api/calendar/day?date=YYYY-MM-DD&subject={subject}`
- **Caller**: Teacher / Admin
- **Response**: Array of Session objects for that day.

### `GET /api/calendar/export.ics`
- **Caller**: Admin only
- **Response**: Streaming `text/calendar` `.ics` file.

