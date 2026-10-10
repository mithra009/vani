# Video Voice-Over Studio

*Working title.*

Upload a video, pick a language and a voice, and get the video back dubbed into Hindi, Tamil, Telugu, Kannada, Malayalam, Marathi, Bengali, Gujarati, Punjabi, English or Hinglish. Each dubbed line starts exactly where the original line started, and the output is exactly as long as the input.


> **Status: planning.** No code yet. The architecture, requirements, challenges and roadmap are in [PLAN.md](PLAN.md).

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

## Responsible use
Only dub videos you own or have permission to use. Only clone a voice with its owner's consent. Cloned output is labelled as AI-generated. Demo material uses self-recorded, synthetic content only.
