# RollCall AI — Institutional Attendance Specification

## 1. System Vision & Architecture
RollCall AI is a multi-modal attendance aggregation, validation, and reporting platform for academic institutions. It provides a deterministic tool-calling backend decoupled from web clients, supporting:
- Ingestion of CSV spreadsheets and attendance sheet photos.
- Strict four-state attendance modeling: `PRESENT`, `ABSENT`, `PENDING`, `UNREVIEWED`.
- Confirmed attendance formula: `PRESENT / (PRESENT + ABSENT) * 100` (unreviewed marks are never forced into binary assumptions).
- Role-Based Access Control (RBAC): `ADMIN`, `FACULTY`, `VIEWER`.
- Dynamic 24-hour lock policy on session editing with immutable audit logging.
- Image quality gating (sharpness and brightness) for attendance photo scans.
- Defaulter recovery calculations and certified PDF exports.

## 2. Four-State Attendance Model
- `PRESENT`: Student verified present in the class.
- `ABSENT`: Student verified absent from the class.
- `PENDING`: Unverified roster entry or awaiting verification.
- `UNREVIEWED`: Ambiguous mark, low OCR confidence (< 0.80), or faint signature.

## 3. Role-Based Access Control (RBAC)
- **ADMIN**:
  - Full access to all departments, teacher-subject mappings, and master records.
  - Can edit sessions older than 24 hours provided a non-empty `reason` is supplied (logged as `ADMIN_OVERRIDE_EVENT`).
  - Access to full audit log, administrative overview, and global defaulter PDF exports.
- **FACULTY**:
  - May create sessions and record attendance strictly for assigned subjects.
  - May edit attendance for own sessions within 24 hours of session creation (`now_utc - created_at_utc <= 24h`).
  - Cannot edit other teachers' sessions or sessions older than 24 hours.
  - Access to own class defaulter lists and subject attendance statistics.
- **VIEWER**:
  - Read-only inspection of confirmed attendance, summaries, and public schedules.

## 4. Policy & Guardrails
### 4.1 24-Hour Edit Lock Policy
- Dynamic lock computation: `is_editable(session_created_at_utc, role, now_utc)`.
- For faculty: editable if `now_utc - session_created_at_utc <= 24 hours`.
- For admin: always editable, but sessions $> 24\text{ hours}$ require an explicit override reason.
- Legacy sessions (created before system deployment) are admin-only for edits.

### 4.2 Append-Only Audit Trail
- Table: `audit_log(log_id, event, actor_id, session_id, usn, old_value, new_value, reason, at_utc)`.
- Database triggers strictly reject `UPDATE` and `DELETE` on `audit_log`.

### 4.3 Safe Two-Step Chat Edits
- Step 1: `prepare_edit_tool` validates session ownership, student enrollment, and edit lock. Stores a single-use pending edit row expiring in 5 minutes.
- Step 2: `confirm_pending` executes only upon explicit user confirmation (`POST /api/chat/confirm`), writing both attendance change and audit log in one atomic transaction.

### 4.4 Blur & Lighting Quality Gate
- Evaluates photo sharpness (Laplacian variance $\ge 100$) and brightness ($60 \le \text{mean pixel} \le 200$).
- Rejects illegible images with `422 QUALITY_REJECTED` and clear guidance for retake.

### 4.5 Defaulter Formula
- Threshold $T = 75.0\%$.
- Classes needed to recover to threshold $T$:
  $$\text{Classes Needed} = \max\left(0,\, \left\lceil \frac{T \times C - 100 \times A}{100 - T} \right\rceil\right)$$
  where $C$ is total conducted classes and $A$ is attended classes.

