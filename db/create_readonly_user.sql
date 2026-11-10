-- db/create_readonly_user.sql
-- Run this in Supabase SQL Editor to create a dedicated read-only role & user

-- 1. Create a read-only role
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'readonly_user') THEN
        CREATE ROLE readonly_user WITH LOGIN PASSWORD 'YOUR_SECURE_READONLY_PASSWORD';
    END IF;
END
$$;

-- 2. Grant connection and usage on schema
GRANT CONNECT ON DATABASE postgres TO readonly_user;
GRANT USAGE ON SCHEMA public TO readonly_user;

-- 3. Grant SELECT strictly on the 4 allowed tables only
GRANT SELECT ON TABLE public.students TO readonly_user;
GRANT SELECT ON TABLE public.rooms TO readonly_user;
GRANT SELECT ON TABLE public.sessions TO readonly_user;
GRANT SELECT ON TABLE public.attendance TO readonly_user;

-- 4. Ensure future tables or other operations are restricted by default
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM readonly_user;

