-- Automatic overlap fixing: when two voice chunks overlap, both are re-voiced faster in up to three
-- steps (+0.15, +0.25, +0.30 over the speed they had). Safe to re-run.
--   fit_step        steps taken so far (0 = untouched, 3 = gave up)
--   fit_base_speed  the speed before the first step, restored when the user edits the chunk
--   fit_note        what happened, shown to the user

alter table public.chunks add column if not exists fit_step smallint not null default 0;
alter table public.chunks add column if not exists fit_base_speed numeric(4, 3);
alter table public.chunks add column if not exists fit_note text;
