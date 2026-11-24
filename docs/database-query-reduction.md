# Database load reduction

The dashboard hit the database far more often than necessary. Fixes below are
in the backend; the front-end GET cache (60s, stale-while-revalidate) and the
single persistent app shell stop repeat requests on every tab switch.

| Endpoint | Before | After |
|---|---|---|
| `GET /api/v1/analytics/overview` | 1 + one joined attendance query **per session ever created** | 1 scoped joined query (`_attendance_records_in_scope`) |
| `GET /api/v1/analytics/date/{date}/summary` | 1 + one query per session on that date | 1 scoped joined query with the date predicate pushed into SQL |
| `GET /api/v1/sessions` | Ran the multi-query timetable initialiser and committed on **every** list request | Runs initialisation only when the requested day has no sessions |
| `GET /api/v1/exams/{exam_id}/summary/room-wise` | 1 + 2×rooms queries (seating per room + lazy invigilator per room) | 1 seating query for the exam + 1 eager-loaded rooms query |

Session visibility is enforced by the same `session_scope_condition` used by
the session and attendance endpoints, so scoping was not weakened.

Files: `backend/app/routers/analytics.py`, `sessions.py`, `exams.py`.
Verified with `test_analytics_api.py`, `test_n6b_session_listing_gaps.py`,
`test_exams.py`, `test_summary_tool_simple.py`.
