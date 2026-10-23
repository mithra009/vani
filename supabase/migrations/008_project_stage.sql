-- Which step of generation a project is on (audio | transcribe | chunk | translate), so the
-- editor can show progress before any chunks exist. Null when idle. Safe to re-run.

alter table public.editor_projects add column if not exists stage text;
