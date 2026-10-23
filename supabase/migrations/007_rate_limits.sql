-- Fair-share rate limiting of the shared Gnani/Gemini keys (editor_service/ratelimit.py).
-- One row per provider call; rows older than the window are deleted as calls are made.
-- Safe to re-run.

create table if not exists public.provider_calls (
  id         bigint generated always as identity primary key,
  provider   text not null,            -- gnani_tts | gnani_stt | gemini
  owner_id   uuid not null,
  at         timestamptz not null default now()
);
create index if not exists provider_calls_window_idx on public.provider_calls (provider, at);
create index if not exists provider_calls_owner_idx on public.provider_calls (provider, owner_id, at);

-- Fair claiming looks up each owner's running jobs.
create index if not exists editor_jobs_owner_status_idx on public.editor_jobs (owner_id, status);

alter table public.provider_calls enable row level security;   -- service role only; no browser access
