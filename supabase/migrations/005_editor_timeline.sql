-- Editor service, phase 2: timeline document, its op log, and per-project music (C11-proposal).
-- Safe to re-run.

create table if not exists public.timelines (
  project_id  uuid primary key references public.editor_projects (id) on delete cascade,
  owner_id    uuid not null references auth.users (id),
  version     int  not null default 1,
  doc         jsonb not null,
  updated_at  timestamptz not null default now()
);

-- Append-only: every accepted batch, for audit and recovery.
create table if not exists public.timeline_ops (
  project_id  uuid not null references public.editor_projects (id) on delete cascade,
  version     int  not null,                    -- the version this batch produced
  ops         jsonb not null,
  created_at  timestamptz not null default now(),
  primary key (project_id, version)
);

create table if not exists public.project_media (
  id          uuid primary key default gen_random_uuid(),
  project_id  uuid not null references public.editor_projects (id) on delete cascade,
  owner_id    uuid not null references auth.users (id),
  storage_key text not null,                    -- {owner}/projects/{project}/music/{id}.{ext}
  filename    text not null check (length(filename) between 1 and 200),
  duration_s  numeric(10, 3) not null check (duration_s > 0),
  status      text not null default 'INITIATED' check (status in ('INITIATED', 'READY')),
  created_at  timestamptz not null default now()
);
create index if not exists project_media_project_idx on public.project_media (project_id);

alter table public.timelines     enable row level security;
alter table public.timeline_ops  enable row level security;
alter table public.project_media enable row level security;

drop policy if exists "timelines_select_own" on public.timelines;
create policy "timelines_select_own" on public.timelines for select using (auth.uid() = owner_id);

drop policy if exists "timeline_ops_select_own" on public.timeline_ops;
create policy "timeline_ops_select_own" on public.timeline_ops for select using (exists (
  select 1 from public.editor_projects p where p.id = timeline_ops.project_id and p.owner_id = auth.uid()
));

drop policy if exists "project_media_select_own" on public.project_media;
create policy "project_media_select_own" on public.project_media for select using (auth.uid() = owner_id);

-- Music uploads: common audio types on top of what 002/004 allow.
update storage.buckets
set allowed_mime_types = array(
  select distinct unnest(coalesce(allowed_mime_types, '{}') || array['audio/aac', 'audio/flac', 'audio/x-m4a'])
)
where id = 'media';
