-- =============================================================================
-- Supabase Row Level Security (RLS) Configuration for RollCall AI
-- =============================================================================
-- This script enables Row Level Security (RLS) on all public application tables
-- and establishes granular role-based policies for:
--   1. backend service role / postgres (full administrative bypass)
--   2. readonly_user (strictly scoped SELECT on reporting tables)
--   3. authenticated users (self-service profile, session attendance, pending edits)
--   4. audit_log (strictly append-only; update and delete prohibited)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Enable RLS on all Application Tables
-- -----------------------------------------------------------------------------
ALTER TABLE IF EXISTS public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.students ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.rooms ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.attendance ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.teacher_subjects ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.faculty_subjects ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.audit_chain_head ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.pending_edits ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.login_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.auth_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.auth_refresh_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.security_rate_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.security_decoys ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.colleges ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.departments ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.academic_years ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.semesters ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.sections ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.subjects ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.department_staff ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.timetables ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.timetable_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.session_allocations ENABLE ROW LEVEL SECURITY;

-- -----------------------------------------------------------------------------
-- 2. Service Role Bypass Policies (Full Access for Backend Engine)
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    tbl text;
    tbls text[] := ARRAY[
        'users', 'students', 'rooms', 'sessions', 'attendance',
        'teacher_subjects', 'faculty_subjects', 'audit_log', 'audit_chain_head',
        'pending_edits', 'login_attempts', 'auth_sessions', 'auth_refresh_tokens',
        'security_rate_limits', 'security_decoys', 'colleges', 'departments',
        'academic_years', 'semesters', 'sections', 'batches', 'subjects',
        'department_staff', 'timetables', 'timetable_entries', 'session_allocations'
    ];
BEGIN
    FOREACH tbl IN ARRAY tbls LOOP
        -- Drop existing service role policy if present to make idempotent
        EXECUTE format('DROP POLICY IF EXISTS service_role_all_%I ON public.%I', tbl, tbl);
        -- Allow service_role / postgres complete access
        EXECUTE format(
            'CREATE POLICY service_role_all_%I ON public.%I FOR ALL TO service_role, postgres USING (true) WITH CHECK (true)',
            tbl, tbl
        );
    END LOOP;
END
$$;

-- -----------------------------------------------------------------------------
-- 3. Readonly User Policies (Scoped SELECT on Core Tables)
-- -----------------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'readonly_user') THEN
        DROP POLICY IF EXISTS readonly_select_students ON public.students;
        CREATE POLICY readonly_select_students ON public.students FOR SELECT TO readonly_user USING (true);

        DROP POLICY IF EXISTS readonly_select_rooms ON public.rooms;
        CREATE POLICY readonly_select_rooms ON public.rooms FOR SELECT TO readonly_user USING (true);

        DROP POLICY IF EXISTS readonly_select_sessions ON public.sessions;
        CREATE POLICY readonly_select_sessions ON public.sessions FOR SELECT TO readonly_user USING (true);

        DROP POLICY IF EXISTS readonly_select_attendance ON public.attendance;
        CREATE POLICY readonly_select_attendance ON public.attendance FOR SELECT TO readonly_user USING (true);
    END IF;
END
$$;

-- -----------------------------------------------------------------------------
-- 4. Public / Reference Data Policies (Authenticated Read Access)
-- -----------------------------------------------------------------------------
-- Reference tables can be read by any authenticated client
DO $$
DECLARE
    ref_tbl text;
    ref_tbls text[] := ARRAY[
        'students', 'rooms', 'subjects', 'colleges', 'departments',
        'academic_years', 'semesters', 'sections', 'batches',
        'timetables', 'timetable_entries'
    ];
BEGIN
    FOREACH ref_tbl IN ARRAY ref_tbls LOOP
        EXECUTE format('DROP POLICY IF EXISTS authenticated_read_%I ON public.%I', ref_tbl, ref_tbl);
        EXECUTE format(
            'CREATE POLICY authenticated_read_%I ON public.%I FOR SELECT TO authenticated USING (true)',
            ref_tbl, ref_tbl
        );
    END LOOP;
END
$$;

-- -----------------------------------------------------------------------------
-- 5. User Self-Service & Profile Access
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS users_read_own ON public.users;
CREATE POLICY users_read_own ON public.users
    FOR SELECT TO authenticated
    USING (
        (auth.uid())::text = user_id
        OR role = 'ADMIN'
    );

DROP POLICY IF EXISTS users_update_own ON public.users;
CREATE POLICY users_update_own ON public.users
    FOR UPDATE TO authenticated
    USING ((auth.uid())::text = user_id)
    WITH CHECK ((auth.uid())::text = user_id);

-- -----------------------------------------------------------------------------
-- 6. Sessions & Attendance Policies
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS sessions_select_authenticated ON public.sessions;
CREATE POLICY sessions_select_authenticated ON public.sessions
    FOR SELECT TO authenticated
    USING (true);

DROP POLICY IF EXISTS sessions_insert_faculty ON public.sessions;
CREATE POLICY sessions_insert_faculty ON public.sessions
    FOR INSERT TO authenticated
    WITH CHECK (
        teacher_id IS NULL 
        OR (auth.uid())::text = teacher_id 
        OR (auth.uid())::text = coordinator_faculty_id
    );

DROP POLICY IF EXISTS attendance_select_authenticated ON public.attendance;
CREATE POLICY attendance_select_authenticated ON public.attendance
    FOR SELECT TO authenticated
    USING (true);

DROP POLICY IF EXISTS attendance_insert_authenticated ON public.attendance;
CREATE POLICY attendance_insert_authenticated ON public.attendance
    FOR INSERT TO authenticated
    WITH CHECK (true);

DROP POLICY IF EXISTS attendance_update_authenticated ON public.attendance;
CREATE POLICY attendance_update_authenticated ON public.attendance
    FOR UPDATE TO authenticated
    USING (true)
    WITH CHECK (true);

-- -----------------------------------------------------------------------------
-- 7. Teacher-Subject Assignments Policies
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS teacher_subjects_read_authenticated ON public.teacher_subjects;
CREATE POLICY teacher_subjects_read_authenticated ON public.teacher_subjects
    FOR SELECT TO authenticated
    USING (true);

DROP POLICY IF EXISTS faculty_subjects_read_authenticated ON public.faculty_subjects;
CREATE POLICY faculty_subjects_read_authenticated ON public.faculty_subjects
    FOR SELECT TO authenticated
    USING (true);

-- -----------------------------------------------------------------------------
-- 8. Pending Edits (Self-Service 5-minute Confirmation Flow)
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS pending_edits_select_owner ON public.pending_edits;
CREATE POLICY pending_edits_select_owner ON public.pending_edits
    FOR SELECT TO authenticated
    USING ((auth.uid())::text = user_id);

DROP POLICY IF EXISTS pending_edits_insert_owner ON public.pending_edits;
CREATE POLICY pending_edits_insert_owner ON public.pending_edits
    FOR INSERT TO authenticated
    WITH CHECK ((auth.uid())::text = user_id);

DROP POLICY IF EXISTS pending_edits_update_owner ON public.pending_edits;
CREATE POLICY pending_edits_update_owner ON public.pending_edits
    FOR UPDATE TO authenticated
    USING ((auth.uid())::text = user_id)
    WITH CHECK ((auth.uid())::text = user_id);

-- -----------------------------------------------------------------------------
-- 9. Audit Log (Append-Only; Strictly Prohibit Alteration)
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS audit_log_insert_authenticated ON public.audit_log;
CREATE POLICY audit_log_insert_authenticated ON public.audit_log
    FOR INSERT TO authenticated
    WITH CHECK (true);

DROP POLICY IF EXISTS audit_log_select_admin ON public.audit_log;
CREATE POLICY audit_log_select_admin ON public.audit_log
    FOR SELECT TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.users
            WHERE users.user_id = (auth.uid())::text AND users.role = 'ADMIN'
        )
    );

-- Prohibit UPDATE and DELETE on audit_log for anyone (even authenticated users)
DROP POLICY IF EXISTS audit_log_no_update ON public.audit_log;
CREATE POLICY audit_log_no_update ON public.audit_log
    FOR UPDATE TO authenticated
    USING (false);

DROP POLICY IF EXISTS audit_log_no_delete ON public.audit_log;
CREATE POLICY audit_log_no_delete ON public.audit_log
    FOR DELETE TO authenticated
    USING (false);

