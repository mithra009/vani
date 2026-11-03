-- Nothing in Vani reads tables through Supabase's REST API: the services connect as postgres,
-- and the browser only uses Supabase for sign-in. So the two public API roles (anon, whose key
-- ships in the frontend, and authenticated) get no rights on the app's tables. RLS already kept
-- their rows private, but TRUNCATE ignores RLS. Future tables get no rights either. Safe to re-run.

revoke all on all tables    in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke all on all functions in schema public from anon, authenticated;

alter default privileges in schema public revoke all on tables    from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;
alter default privileges in schema public revoke all on functions from anon, authenticated;
