# Video Voice-Over Studio

*Working title.*

Upload a video, pick a language and a voice, and get the video back dubbed into Hindi, Tamil, Telugu, Kannada, Malayalam, Marathi, Bengali, Gujarati, Punjabi, English or Hinglish. Each dubbed line starts exactly where the original line started, and the output is exactly as long as the input.


> **Status:** Working implementation. See the [system diagram](SYSTEM_DIAGRAM.md) for the current component architecture and job flow. The original requirements, design decisions, and roadmap are in [PLAN.md](PLAN.md).

---

## How it works

```
video ─► extract audio ─► Prisma v2.5 Batch STT ─► detect each line's emotion
      ─► you review the transcript and emotions
      ─► Gemini 3.5 Flash-Lite translates each line to fit its time slot, keeping emotion cues
      ─► Timbre v2.5 (or a clone of the speaker's voice) speaks each line
      ─► fit each line to its slot (speed + pitch-preserving stretch)
      ─► place lines at their original timestamps ─► mix with the original audio ─► MP4 + subtitles
```

1. **Transcribe:** Gnani Prisma v2.5 Batch STT returns timestamped segments, and can tell multiple speakers apart.
2. **Detect emotion:** each line is labelled (e.g. happy, angry, sad, whispering, laughing) from how it sounds (pitch, loudness, pace, compared with the speaker's normal voice) and what is said.
3. **Review:** fix any recognition mistakes or wrong emotion labels before anything is spent on synthesis.
4. **Translate to fit:** Gemini 3.5 Flash-Lite translates each line within a character budget worked out from the line's duration and the chosen voice's speaking rate. It also places emotion cues such as `<laugh>`, `<whispers>` or `<shouting>` where they belong in the translated line.
5. **Speak with feeling:** pick one of Gnani's 42 Timbre v2.5 voices, or clone the original speaker from a 5–30 s sample (with consent). The voice stays the same throughout; emotion comes from Timbre's audio tags, speed and wording, so a laugh in the original is a laugh in the dub.
6. **Fit:** each line is sped up or slowed within natural limits (Timbre `speed` 0.85–1.15 plus ffmpeg `atempo`). Lines that still don't fit get a shorter translation or are flagged for you.
7. **Assemble:** every line is placed at its *own* start time, so errors can't add up over a long video. The original audio is lowered under the dub, the video stream is copied untouched, and the audio is cut to the exact video length.

## Models used

| Model | Used for |
|---|---|
| Prisma v2.5 (Batch STT) | Timestamped transcription, speaker diarization |
| Timbre v2.5 (TTS) | Persona voices in 10 languages + Hinglish |
| Voice-clone TTS | Dubbing in the original speaker's voice |
| Gemini 3.5 Flash-Lite (Google) | Length-aware translation, emotion labelling from the transcript. A stand-in until the organisers confirm whether Gnani's Evon v3.3 is required; it can be swapped through one interface |

## What it does not do
- **Lip sync:** mouths won't match the new language.
- **Subtle emotion:** clear emotions (laughing, shouting, whispering, sighing, excitement, sadness) carry over; sarcasm and irony mostly don't.
- **Languages outside Gnani's ten plus Hinglish.**
- **Real-time dubbing:** it's an upload-and-wait tool.
- **Music separation:** the original track is lowered (or muted) under the dub, not removed.

## Requirements
- Python 3.12, Node 20+, ffmpeg 6+ on PATH
- A Gnani API key in `.env` as `GNANI_API_KEY`
- A Google AI Studio key in `.env` as `GOOGLE_API_KEY` (Gemini 3.5 Flash-Lite)

## Setup and running

### Everything at once (Docker)

Needs Docker Desktop running. Postgres, Auth and Storage stay on Supabase; Docker runs the
six app processes: `backend` (:8010), `media-api` (:8020) + `media-worker`,
`editor-api` (:8030) + `editor-worker`, and `frontend` (nginx on :8080, proxying `/api`).

1. **`.env` at the repo root** with at least `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`,
   `SUPABASE_SECRET_KEY` and `DATABASE_URL`. `DATABASE_URL` must be the direct connection
   (:5432) or the session pooler, **not** the transaction pooler (:6543). Add `GNANI_API_KEY`
   and `GOOGLE_API_KEY` only for real (paid) runs. `.env` is read at runtime and never copied
   into an image.
2. **Apply the migrations once**, in order, in Supabase → SQL Editor: paste and run each file in
   `supabase/migrations/` (`001` … `006`). They are safe to re-run. If one is missing, the editor
   API and worker stop at startup and name the file to apply.
3. **Start:**
   ```
   docker compose up --build
   ```
   Open http://localhost:8080. If Supabase Auth restricts redirect URLs, add
   `http://localhost:8080` there.

**Credits:** every service runs with fake providers by default (`FAKE_PROVIDERS=1`): no Gnani or
Gemini calls, no credits. For a real run:
```
# PowerShell
$env:FAKE_PROVIDERS="0"; docker compose up --build
# bash
FAKE_PROVIDERS=0 docker compose up --build
```

Useful commands:
```
docker compose up -d --build          # run in the background
docker compose logs -f editor-worker  # follow one service
docker compose ps                     # health of each service
docker compose up --build frontend    # rebuild after frontend changes
docker compose down                   # stop (add -v to also delete the backend's storage volume)
```

The backend's `storage/` (jobs, media, paid-result cache) lives in the `vani-storage` volume.
The frontend waits until the three APIs report healthy, so a failing API keeps it from starting:
check `docker compose ps` and that service's logs.

### Frontend (React + Vite)
```
cd frontend
npm install
npm run dev        # http://localhost:5173
```
Without the backend, the app runs in **demo mode**: the pipeline is simulated in the browser with sample lines, your video is returned undubbed, and no credits are used. A "Demo mode" pill in the nav shows this. Once the FastAPI backend is running on port 8010, the dev server proxies `/api` to it and the pill shows "Live".

### Backend (FastAPI)
```
.venv\Scripts\python -m pip install -r backend\requirements.txt
.venv\Scripts\python -m uvicorn backend.app.main:app --port 8010
```
Needs `GNANI_API_KEY` and `GOOGLE_API_KEY` in `.env`, and ffmpeg on PATH. Data is stored in `storage/` (jobs, media, and a cache of every paid API result, so re-runs never pay twice).

**Free mode for development:** set `FAKE_PROVIDERS=1` (PowerShell: `$env:FAKE_PROVIDERS="1"`) before starting. Gnani and Gemini are replaced by local stand-ins: speech detection on your real audio, tones for voices, placeholder translations. The whole pipeline, including timing, fitting and ffmpeg mixing, runs for real at zero cost.

Tests (always use fake providers):
```
.venv\Scripts\python -m pytest backend\tests
```

### Media service (library uploads + processing worker)
The Library tab is backed by a second FastAPI app plus a background worker:
direct-to-Supabase uploads (signed URLs), a `jobs` queue in Postgres
(`SELECT ... FOR UPDATE SKIP LOCKED`), and FFmpeg probe/thumbnail/proxy tasks.

```
# 1. apply the schema (assets, jobs, private "media" bucket)
supabase link --project-ref <ref>      # once
supabase db push                       # runs supabase/migrations/*.sql
#    (or paste supabase/migrations/002_media_assets.sql into the SQL editor)

# 2. set DATABASE_URL in .env — Supabase direct connection (:5432) or session
#    pooler, NOT the transaction pooler (:6543)

# 3. install + run both processes (plus the backend on :8010 and `npm run dev`)
.venv\Scripts\python -m pip install -r media_service\requirements.txt
.venv\Scripts\python -m uvicorn media_service.main:app --port 8020
.venv\Scripts\python -m media_service.worker
```

The Vite dev server proxies `/api/uploads/*` and `/api/assets/*` to :8020 and the
rest of `/api` to :8010. The worker runs FFmpeg/FFprobe in isolated subprocesses;
proxies are capped at 1280 px on the longest side and keep the source's duration,
timestamps and orientation. Soft-deleted assets are purged from storage by a
cleanup job after a short grace period.

Tests:
```
.venv\Scripts\python -m pytest media_service\tests
```

### Editor service (chunks, timeline, export)

Design: `docs/design/PROJECT_EDITOR_DESIGN.md`. Needs the media service (videos come from
the Library) and the same `DATABASE_URL`.

```
# 1. apply supabase/migrations/004_editor_projects.sql, 005_editor_timeline.sql,
#    006_editor_exports.sql (SQL editor, in order)

# 2. run the API (:8030) and the worker. FAKE_PROVIDERS defaults to 1 here:
#    no Gnani/Gemini calls, no credits. Set FAKE_PROVIDERS=0 only for a pilot.
.venv\Scripts\python -m uvicorn editor_service.main:app --port 8030
.venv\Scripts\python -m editor_service.worker
```

The Vite dev server proxies `/api/editor/*` to :8030. Open **Editor** in the nav.

Tests (the DB tests need a throwaway Postgres; they wipe it):
```
.venv\Scripts\python -m pytest editor_service\tests
set DATABASE_URL_TEST=postgresql://postgres@127.0.0.1:5432/vani_test
.venv\Scripts\python -m pytest editor_service\tests
```

## Responsible use
Only dub videos you own or have permission to use. Only clone a voice with its owner's consent. Cloned output is labelled as AI-generated. Demo material uses self-recorded, synthetic content only.


```
system startup

.venv\Scripts\python -m uvicorn backend.app.main:app --port 8010
.venv\Scripts\python -m uvicorn media_service.main:app --port 8020
.venv\Scripts\python -m media_service.worker
(Vite should still be up — npm run dev in frontend/ if not.)



#	Command	Purpose
1	$env:FAKE_PROVIDERS="0"; .venv\Scripts\python -m uvicorn backend.app.main:app --port 8010	Pipeline API
2	$env:FAKE_PROVIDERS="1"; .venv\Scripts\python -m uvicorn media_service.main:app --port 8020	Library/uploads API
3	$env:FAKE_PROVIDERS="1"; .venv\Scripts\python -m media_service.worker	FFmpeg probe/thumbnail worker
4	$env:FAKE_PROVIDERS="1"; .venv\Scripts\python -m uvicorn editor_service.main:app --port 8030	Editor API
5	$env:FAKE_PROVIDERS="1"; .venv\Scripts\python -m editor_service.worker	Editor export worker
6	cd frontend; npm run dev	UI at http://localhost:5173 (http://localhost:5173) (proxies /api → 8010/8020/8030)
```