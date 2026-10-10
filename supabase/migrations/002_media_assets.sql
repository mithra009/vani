-- Media library: assets + jobs (Postgres-backed queue with SKIP LOCKED).
-- Apply with: supabase db push   (or paste into the Supabase SQL editor).

-- ------------------------------------------------------------------ assets
create table if not exists public.assets (
  id               uuid primary key default gen_random_uuid(),
  project_id       text references public.projects (id) on delete set null,
  owner_id         uuid not null references auth.users (id),
  original_filename text not null,
  storage_key      text not null,               -- opaque: {user_id}/{asset_id}/source.ext
  size_bytes       bigint not null default 0,
  duration_ms      bigint,
  status           text not null default 'INITIATED'
                   check (status in ('INITIATED', 'UPLOADED', 'PROCESSING', 'READY', 'FAILED')),
  metadata_status  text not null default 'PENDING'
                   check (metadata_status in ('PENDING', 'RUNNING', 'READY', 'FAILED')),
  thumbnail_status text not null default 'PENDING'
                   check (thumbnail_status in ('PENDING', 'RUNNING', 'READY', 'FAILED')),
  proxy_status     text not null default 'PENDING'
                   check (proxy_status in ('PENDING', 'RUNNING', 'READY', 'FAILED')),
  metadata         jsonb,
  created_at       timestamptz not null default now(),
  deleted_at       timestamptz
);

create index if not exists assets_owner_idx on public.assets (owner_id, created_at desc);
create index if not exists assets_storage_key_idx on public.assets (storage_key);

-- ------------------------------------------------------------------ jobs
create table if not exists public.jobs (
  id          uuid primary key default gen_random_uuid(),
  asset_id    uuid not null references public.assets (id) on delete cascade,
  kind        text not null check (kind in ('probe', 'thumbnail', 'proxy', 'cleanup')),
  status      text not null default 'PENDING'
              check (status in ('PENDING', 'RUNNING', 'DONE', 'FAILED')),
  attempts    int  not null default 0,
  last_error  text,
  run_after   timestamptz not null default now(),
  created_at  timestamptz not null default now(),
  started_at  timestamptz,
  finished_at timestamptz,
  unique (asset_id, kind)                      -- never double-enqueue a task
);

create index if not exists jobs_claim_idx on public.jobs (status, run_after);

-- ------------------------------------------------------------------ RLS
-- The media service uses the service role (bypasses RLS). These policies let the
-- browser read its own rows directly (e.g. for optional Supabase Realtime).
alter table public.assets enable row level security;
alter table public.jobs   enable row level security;

drop policy if exists "assets_select_own" on public.assets;
create policy "assets_select_own" on public.assets
  for select using (auth.uid() = owner_id);

drop policy if exists "assets_insert_own" on public.assets;
create policy "assets_insert_own" on public.assets
  for insert with check (auth.uid() = owner_id);

drop policy if exists "assets_update_own" on public.assets;
create policy "assets_update_own" on public.assets
  for update using (auth.uid() = owner_id) with check (auth.uid() = owner_id);

drop policy if exists "assets_delete_own" on public.assets;
create policy "assets_delete_own" on public.assets
  for delete using (auth.uid() = owner_id);

drop policy if exists "jobs_select_own" on public.jobs;
create policy "jobs_select_own" on public.jobs
  for select using (exists (
    select 1 from public.assets a where a.id = jobs.asset_id and a.owner_id = auth.uid()
  ));

-- ------------------------------------------------------------------ realtime
-- Optional: lets the frontend subscribe to asset status changes later.
do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'assets'
  ) then
    alter publication supabase_realtime add table public.assets;
  end if;
exception when undefined_object then
  -- Local/self-hosted Postgres without the publication: skip.
  null;
end $$;

-- ------------------------------------------------------------------ storage
-- Private bucket for source videos, thumbnails and proxies.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'media', 'media', false, 524288000,
  array['video/mp4', 'video/quicktime', 'video/webm', 'video/x-matroska', 'image/jpeg']
)
on conflict (id) do nothing;

-- Owners can read/list their own folder (service role bypasses this anyway).
drop policy if exists "media_objects_select_own" on storage.objects;
create policy "media_objects_select_own" on storage.objects
  for select using (
    bucket_id = 'media' and auth.uid()::text = (storage.foldername(name))[1]
  );
