-- Editor service, phase 3: exports (R8, D10). Safe to re-run.

create table if not exists public.exports (
  id               uuid primary key default gen_random_uuid(),
  project_id       uuid not null references public.editor_projects (id) on delete cascade,
  owner_id         uuid not null references auth.users (id),
  timeline_version int  not null,
  format           text not null check (format in ('mp4', 'webm', 'mov', 'mp3', 'wav')),
  height           int  check (height in (480, 720, 1080)),          -- null for audio-only
  audio_mix        text not null default 'full' check (audio_mix in ('full', 'voice')),   -- C13
  captions         text not null default 'none' check (captions in ('none', 'srt', 'vtt', 'burn')),  -- C3
  snapshot         jsonb not null,             -- timeline doc + chunk audio keys + media at request time
  content_key      text not null,              -- same inputs → same file, re-export is free
  status           text not null default 'queued' check (status in ('queued', 'rendering', 'ready', 'failed')),
  progress         real not null default 0,
  warnings         jsonb not null default '[]'::jsonb,
  output_key       text,
  captions_key     text,
  error_code       text,
  error_message    text,
  created_at       timestamptz not null default now(),
  finished_at      timestamptz,
  check ((format in ('mp3', 'wav')) = (height is null)),
  check (format not in ('mp3', 'wav') or captions in ('none', 'srt', 'vtt'))
);
create index if not exists exports_project_idx on public.exports (project_id, created_at desc);

alter table public.exports enable row level security;
drop policy if exists "exports_select_own" on public.exports;
create policy "exports_select_own" on public.exports for select using (auth.uid() = owner_id);

-- Queue: a third job kind.
alter table public.editor_jobs add column if not exists export_id uuid references public.exports (id) on delete cascade;
alter table public.editor_jobs drop constraint if exists editor_jobs_kind_check;
alter table public.editor_jobs add constraint editor_jobs_kind_check check (kind in ('generate', 'tts', 'export'));
alter table public.editor_jobs drop constraint if exists editor_jobs_export_check;
alter table public.editor_jobs add constraint editor_jobs_export_check check ((kind = 'export') = (export_id is not null));

alter table public.artifacts drop constraint if exists artifacts_kind_check;
alter table public.artifacts add constraint artifacts_kind_check check (kind in ('stt_json', 'chunk_wav', 'export'));

update storage.buckets
set allowed_mime_types = array(
  select distinct unnest(coalesce(allowed_mime_types, '{}') || array['video/mp4', 'video/webm', 'video/quicktime',
    'audio/mpeg', 'audio/wav', 'application/x-subrip', 'text/vtt'])
)
where id = 'media';
