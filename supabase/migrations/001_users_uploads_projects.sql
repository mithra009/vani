-- Vani: users, uploads, projects.
-- Run once in Supabase → SQL Editor → New query → paste → Run.
-- Safe to re-run: every statement is idempotent.

-- ---------------------------------------------------------------- users
-- Profile row for each Supabase Auth user (auth.users holds the password).
create table if not exists public.users (
  id          uuid primary key references auth.users (id) on delete cascade,
  username    text not null unique
              check (username ~ '^[a-z0-9][a-z0-9_-]{1,28}[a-z0-9]$'),
  first_name  text not null check (length(trim(first_name)) between 1 and 60),
  last_name   text not null check (length(trim(last_name)) between 1 and 60),
  email       text not null unique check (email = lower(email)),
  created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------- uploads
-- One row per video (or narration) file a user uploads.
create table if not exists public.uploads (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.users (id) on delete cascade,
  kind          text not null default 'video' check (kind in ('video', 'narration', 'voice_sample')),
  filename      text not null,
  size_bytes    bigint not null check (size_bytes >= 0),
  duration_s    double precision,
  storage_path  text not null,
  created_at    timestamptz not null default now()
);
create index if not exists uploads_user_idx on public.uploads (user_id, created_at desc);

-- ---------------------------------------------------------------- projects
-- One row per dubbing / narration project. `data` holds the full job document
-- (segments, voice, stats); the scalar columns are for listing and filtering.
create table if not exists public.projects (
  id          text primary key,
  user_id     uuid not null references public.users (id) on delete cascade,
  upload_id   uuid references public.uploads (id) on delete set null,
  name        text not null,
  mode        text not null check (mode in ('dub', 'narrate')),
  status      text not null,
  src_lang    text,
  tgt_lang    text,
  duration_s  double precision,
  data        jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index if not exists projects_user_idx on public.projects (user_id, created_at desc);

create or replace function public.touch_updated_at() returns trigger
language plpgsql as $$ begin new.updated_at = now(); return new; end $$;
drop trigger if exists projects_touch on public.projects;
create trigger projects_touch before update on public.projects
  for each row execute function public.touch_updated_at();

-- ---------------------------------------------------------------- security
-- The backend uses the secret key (bypasses RLS). These policies stop anyone using the
-- public key from the browser from reading or changing another user's rows.
alter table public.users    enable row level security;
alter table public.uploads  enable row level security;
alter table public.projects enable row level security;

drop policy if exists "own profile" on public.users;
create policy "own profile" on public.users for select using (auth.uid() = id);

drop policy if exists "own uploads" on public.uploads;
create policy "own uploads" on public.uploads for select using (auth.uid() = user_id);

drop policy if exists "own projects" on public.projects;
create policy "own projects" on public.projects for select using (auth.uid() = user_id);

-- Sign-in by username needs to look up the email for a username. Only the backend
-- (secret key) does this; no policy grants it to browsers.
