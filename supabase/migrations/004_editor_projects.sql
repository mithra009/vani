-- Editor service, phase 1: projects, chunks, content-addressed artifacts and the job queue.
-- Apply with: supabase db push   (or paste into the Supabase SQL editor).
-- Safe to re-run: every statement is idempotent.
--
-- New `editor_projects` table instead of altering `projects`: the dubbing backend
-- (backend/app/store.py) still reads and writes `projects`, so both run side by side
-- until the migration in docs/design/PROJECT_EDITOR_DESIGN.md §9 retires the old one.

-- ------------------------------------------------------------------ projects
create table if not exists public.editor_projects (
  id                 uuid primary key default gen_random_uuid(),
  owner_id           uuid not null references auth.users (id),
  asset_id           uuid not null references public.assets (id),
  name               text not null check (length(trim(name)) between 1 and 120),
  input_kind         text not null check (input_kind in ('video_audio', 'script', 'narration')),
  script_text        text check (script_text is null or length(script_text) <= 20000),
  narration_key      text,                       -- {owner}/projects/{id}/narration.{ext}
  src_lang           text not null,
  tgt_lang           text not null,
  voice              jsonb not null,             -- {mode: 'persona', voice_id} (D8)
  duration_s         numeric(10, 3),
  status             text not null default 'draft'
                     check (status in ('draft', 'awaiting_narration', 'generating', 'editing', 'failed')),
  error_code         text,
  error_message      text,
  settings_version   int not null default 1,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  deleted_at         timestamptz,
  check ((input_kind = 'script') = (script_text is not null))
);
create index if not exists editor_projects_owner_idx
  on public.editor_projects (owner_id, created_at desc) where deleted_at is null;

drop trigger if exists editor_projects_touch on public.editor_projects;
create trigger editor_projects_touch before update on public.editor_projects
  for each row execute function public.touch_updated_at();

-- ------------------------------------------------------------------ chunks
create table if not exists public.chunks (
  id               uuid primary key default gen_random_uuid(),
  project_id       uuid not null references public.editor_projects (id) on delete cascade,
  owner_id         uuid not null references auth.users (id),
  idx              int  not null,
  source_text      text not null,
  char_start       int  not null,
  char_end         int  not null check (char_end > char_start),
  text             text not null check (length(trim(text)) > 0),
  anchor_src_s     numeric(10, 3),
  anchor_len_s     numeric(10, 3),
  overflow         boolean not null default false,   -- script placed past the video end (C2)
  emotion_tag      text not null default 'neutral',
  speed            numeric(4, 3) not null default 1.0 check (speed between 0.85 and 1.15),  -- C5
  audio_key        text,
  audio_duration_s numeric(10, 3),
  status           text not null default 'pending'
                   check (status in ('pending', 'generating', 'ready', 'failed')),
  error_code       text,
  error_message    text,
  revision         int  not null default 1,
  updated_at       timestamptz not null default now(),
  unique (project_id, idx)
);

drop trigger if exists chunks_touch on public.chunks;
create trigger chunks_touch before update on public.chunks
  for each row execute function public.touch_updated_at();

-- ------------------------------------------------------------------ artifacts
-- Content-addressed outputs (STT json, chunk wav). Per owner: never shared across users.
create table if not exists public.artifacts (
  owner_id      uuid not null references auth.users (id),
  content_key   text not null,
  kind          text not null check (kind in ('stt_json', 'chunk_wav')),
  storage_key   text not null,
  meta          jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now(),
  last_used_at  timestamptz not null default now(),
  primary key (owner_id, content_key)
);

-- ------------------------------------------------------------------ jobs
-- Same queue shape as public.jobs (002): SELECT ... FOR UPDATE SKIP LOCKED.
-- `generate` = extract → (clean) → stt → chunk → translate → place, then one `tts` per chunk.
create table if not exists public.editor_jobs (
  id              uuid primary key default gen_random_uuid(),
  project_id      uuid not null references public.editor_projects (id) on delete cascade,
  owner_id        uuid not null references auth.users (id),
  kind            text not null check (kind in ('generate', 'tts')),
  chunk_id        uuid references public.chunks (id) on delete cascade,
  chunk_revision  int,                          -- stale-result guard for tts
  status          text not null default 'PENDING'
                  check (status in ('PENDING', 'RUNNING', 'DONE', 'FAILED', 'SKIPPED')),
  attempts        int  not null default 0,
  error_code      text,
  last_error      text,
  run_after       timestamptz not null default now(),
  created_at      timestamptz not null default now(),
  started_at      timestamptz,
  finished_at     timestamptz,
  check ((kind = 'tts') = (chunk_id is not null))
);
create index if not exists editor_jobs_claim_idx on public.editor_jobs (status, run_after);
create index if not exists editor_jobs_project_idx on public.editor_jobs (project_id);

-- ------------------------------------------------------------------ RLS
-- The editor service uses the service role (bypasses RLS); every query also filters by owner.
alter table public.editor_projects enable row level security;
alter table public.chunks          enable row level security;
alter table public.artifacts       enable row level security;
alter table public.editor_jobs     enable row level security;

drop policy if exists "editor_projects_select_own" on public.editor_projects;
create policy "editor_projects_select_own" on public.editor_projects
  for select using (auth.uid() = owner_id);

drop policy if exists "chunks_select_own" on public.chunks;
create policy "chunks_select_own" on public.chunks
  for select using (auth.uid() = owner_id);

drop policy if exists "artifacts_select_own" on public.artifacts;
create policy "artifacts_select_own" on public.artifacts
  for select using (auth.uid() = owner_id);

drop policy if exists "editor_jobs_select_own" on public.editor_jobs;
create policy "editor_jobs_select_own" on public.editor_jobs
  for select using (auth.uid() = owner_id);
