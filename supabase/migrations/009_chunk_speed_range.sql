-- Chunk speed 0.5–2.0× (was 0.85–1.15). Gnani still gets its own 0.85–1.15 range; the worker
-- stretches the rest with ffmpeg atempo. Safe to re-run.

alter table public.chunks drop constraint if exists chunks_speed_check;
alter table public.chunks add constraint chunks_speed_check check (speed between 0.5 and 2.0);
