# Supabase RLS review (audit gap — NOT TESTED)

The faculty audit could not verify Supabase Row Level Security. API-layer
authorization tests do **not** prove RLS boundaries, so this item must remain
marked **NOT TESTED** until someone with read-only SQL access completes the
checks below and records the outcomes.

## 1. Read-only policy inventory

Run in the Supabase SQL editor with an account that can read catalog tables:

```sql
-- Which tables actually enforce RLS?
select relname as table_name,
       relrowsecurity as rls_enabled,
       relforcerowsecurity as rls_forced
from pg_class
where relnamespace = 'public'::regnamespace and relkind = 'r'
order by relname;

-- All current policies, with the roles and commands they apply to.
select schemaname, tablename, policyname, permissive, roles,
       cmd, qual as using_expression, with_check
from pg_policies
where schemaname = 'public'
order by tablename, policyname;
```

Expected for faculty-facing tables (`users`, `sessions`, `attendance`,
`faculty_subjects`, `room_assignments`, `exam_seating`, ...): RLS enabled and
policies that restrict rows to the authenticated user's `user_id` or their
assigned subjects, plus an explicit admin policy.

## 2. Role-scoped direct checks

For each relevant table, test SELECT / INSERT / UPDATE / DELETE as the three
audit identities (`test_faculty`, `faculty_ai`, `faculty_cn`) using
`SET LOCAL role authenticated; SET LOCAL request.jwt.claims = ...` (or the
Supabase client with each user's JWT). Record, per table and operation:

- policy name that allowed/denied the row,
- whether a cross-faculty row was visible or modifiable,
- expected vs actual outcome.

Never log real JWTs, passwords or student personal data in the evidence file.

## 3. Evidence to attach to the audit ticket

- policy names, table names, test identities and outcomes,
- SQL client/version, timestamp, and the git commit hash of the API under test,
- explicit statement that any unavailable check stays `NOT TESTED`.

## 4. Local helper for the related credential defect (V-02)

After correcting the `faculty_ai` provisioning value, confirm the exact
credential without printing it:

```powershell
$env:VERIFY_USER_ID = "faculty_ai"
$env:VERIFY_PASSWORD = "<intended password>"
python backend/scripts/verify_credential.py
Remove-Item Env:VERIFY_PASSWORD
```

A PASS result means login must succeed with that exact string; it must fail
with leading/trailing spaces or any punctuation/whitespace mutation.
