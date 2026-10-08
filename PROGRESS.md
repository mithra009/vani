# Implementation Planner & Progress Tracker

Companion to [PLAN.md](PLAN.md); section numbers (§) refer to it.
**Deadline: 10 Nov 2026, 11:59 PM IST. Target: submit on 9 Nov.**

## How to use this file
- Each task has an ID, an owner, a status and **evidence**. A task is ✅ only when the evidence column links to something real: a test result, a file, a measured number or a recording.
- Status: ⬜ not started · 🟨 in progress · ✅ done · ⛔ blocked · ➖ dropped
- 💳 means the task **spends Gnani credits**. Don't run it until the credit budget allows (see the credit ledger below).
- Update the **Dashboard** and add a line to the **Log** at the end of every work session.

---

## Dashboard

| Phase | Window | Status | Done / total | Blocker |
|---|---|---|---|---|
| P0 Setup & API verification | Oct 8–11 | 🟨 | 2 / 14 | Gemini key, Discord answers |
| P1 Backend skeleton | Oct 11–14 | ⬜ | 0 / 9 | none |
| P2 Translate + fit engine | Oct 15–19 | ⬜ | 0 / 10 | P0 (LLM check) |
| P2b Emotion transfer | Oct 17–21 | ⬜ | 0 / 9 | P0 emotion experiments |
| P3 Assemble / mix / mux | Oct 19–21 | ⬜ | 0 / 7 | none |
| P4 Frontend | Oct 8 (early) | 🟨 | 11 / 12 | Live API (P1) to verify P4.11 |
| P5 Voice clone | Oct 25–28 | ⬜ | 0 / 6 | P0 clone check |
| P6 Quality & evaluation | Oct 29–Nov 4 | ⬜ | 0 / 9 | P2–P5 |
| v2 Multi-speaker (stretch) | Nov 1–4 | ⬜ | 0 / 4 | P6 green |
| P7 Submission | Nov 5–9 | ⬜ | 0 / 8 | everything above |

**Overall: 13 / 88 tasks.** Critical path: P0 API checks → P2 translation → P6 evaluation → P7 demo video.

---

## Decisions & open questions

| # | Question | Status | Answer / decision | Date |
|---|---|---|---|---|
| D1 | Is Gemini allowed for translation, or must it be Evon? Is there a hosted Evon endpoint? (Ask on Discord) | 🟨 interim | **Using Gemini 3.5 Flash-Lite (`gemini-3.5-flash-lite`) for now**, behind a swappable interface | Oct 8 |
| D2 | Is a non-Gnani music-separation model (Demucs) allowed? (Discord) | ⬜ open | Default: duck the original audio | |
| D3 | Demo languages (source → targets) | ⬜ open | Proposal: Hinglish/English → Hindi, Tamil, Kannada | |
| D4 | Team: solo or two people, and who owns which phases | ⬜ open | | |
| D5 | If Evon becomes required: organiser endpoint / Inya agent / self-host (§4.3) | ➖ deferred | Only needed if D1 says Gnani-only | |
| D6 | Project name (repo is `vani`) | ⬜ open | | |

---

## P0: Setup & API verification (Oct 8–11)

**Goal:** every assumption the pipeline depends on is checked on real calls, with as few credits as possible.

| ID | Task | Owner | Status | Evidence |
|---|---|---|---|---|
| P0.1 | Git repo set up, pushing as mithra009 | | ✅ | `origin` = github.com/mithra009/vani, auth checked |
| P0.2 | ffmpeg available | | ✅ | ffmpeg 8.0.1 on PATH |
| P0.3 | Pull remote `main` and merge with the local PLAN/README edits | | ⬜ | |
| P0.4 | Post D1 + D2 on the hackathon Discord | | ⬜ | link to the post |
| P0.5 | Record three 60 s **synthetic** test clips (self-recorded, consented): calm talk, an expressive clip (laugh, shout, whisper, sigh, acted on purpose), a noisy room | | ⬜ | `samples/` |
| P0.6 | 💳 Batch STT on clip 1: create, start, poll, fetch. Check segment `start_time`/`end_time` units and accuracy by ear | | ⬜ | JSON saved + notes |
| P0.7 | 💳 Batch STT language check: does gu-IN / pa-IN work (C13)? | | ⬜ | |
| P0.8 | 💳 Timbre: one line per demo target language with one voice each; note the leading/trailing silence | | ⬜ | wavs + durations |
| P0.9 | 💳 Emotion experiment 1: same line × 7 tags × demo languages (§5.9.5) | | ⬜ | listening notes table |
| P0.10 | 💳 Emotion experiment 2: measure the time each tag adds (`<laugh>`, `<sigh>`, `<pauses>`) | | ⬜ | numbers in §5.9.3 |
| P0.11 | 💳 Voice-clone embedding from a 15 s self-recording, and one clone TTS line | | ⬜ | wav |
| P0.12 | 💳 Emotion experiments 3 + 4: calm vs excited clone; tags with a clone | | ⬜ | listening notes |
| P0.13 | Gemini 3.5 Flash-Lite: add `GOOGLE_API_KEY`; translate 10 sentences into each demo language with the length-budget prompt and JSON schema | | ⬜ | outputs + time per call |
| P0.14 | Fill the **credit ledger** from dashboard usage after P0.6–P0.12 | | ⬜ | ledger below |

**Exit:** the PLAN §5.9.3 table is updated with what actually works; D1, D3 and D5 are decided; the per-call credit cost is known.

---

## P1: Backend skeleton (Oct 11–14)

| ID | Task | Owner | Status | Evidence |
|---|---|---|---|---|
| P1.1 | Project layout (`backend/`, `frontend/`, `storage/`), `requirements.txt`, `.env.example` | | ⬜ | |
| P1.2 | FastAPI app + SQLite schema (jobs, segments, speakers, cache, voice_calibration) (§6) | | ⬜ | |
| P1.3 | Job runner: asyncio queue, stage checkpoints, resume after a crash (N6) | | ⬜ | test: kill mid-job, resume |
| P1.4 | Content-hash cache wrapper for every paid call (F11) | | ⬜ | unit test: second call costs 0 |
| P1.5 | Gnani client: Batch STT, TTS, clone embedding, clone TTS; retries with backoff on 429/5xx (C12) | | ⬜ | tests with mocked HTTP |
| P1.6 | Ingest stage: ffprobe checks, 16 kHz mono + 48 kHz extract (§5.1) | | ⬜ | test on 3 sample formats |
| P1.7 | Transcribe stage + segment normalisation: merge < 1.2 s, split > 12 s at energy pauses, slot computation (§5.2) | | ⬜ | unit tests |
| P1.8 | REST endpoints: `POST /jobs`, `GET /jobs/{id}`, `GET/PATCH /segments`, SSE `/events` | | ⬜ | curl transcript |
| P1.9 | 💳 End to end: upload clip 1 and get edited segments back through the API | | ⬜ | |

---

## P2: Translate + fit engine (Oct 15–19)

| ID | Task | Owner | Status | Evidence |
|---|---|---|---|---|
| P2.1 | `Translator` / `EmotionLabeler` interface (swappable backend); Gemini 3.5 Flash-Lite client | | ⬜ | |
| P2.2 | 💳 Voice calibration: characters per second per voice at speed 1.0, cached (§5.4) | | ⬜ | table in DB |
| P2.3 | Budgeted translation prompt: batches of 20, JSON, `natural` + `short` variants, names and numbers kept | | ⬜ | 20-segment sample |
| P2.4 | Duration predictor (text + tag time) and speed selection (§5.5 step 1) | | ⬜ | unit tests |
| P2.5 | Silence trim + duration measurement | | ⬜ | unit tests |
| P2.6 | Fit decision: place / `atempo` ≤ 1.15 / short variant / borrow ≤ 300 ms / flag; cap total about 1.3× | | ⬜ | unit tests, every branch covered |
| P2.7 | Pitch-preserving stretch via ffmpeg `atempo` | | ⬜ | pitch unchanged by ear |
| P2.8 | Segment-level regenerate endpoint | | ⬜ | |
| P2.9 | 💳 Pilot dub of clip 1 into 1 language | | ⬜ | overrun count, stretch p95 |
| P2.10 | Exit check: **0 overruns > 1.25×** on the pilot | | ⬜ | numbers |

---

## P2b: Emotion transfer (Oct 17–21)

| ID | Task | Owner | Status | Evidence |
|---|---|---|---|---|
| P2b.1 | Acoustic features per segment: pitch (pYIN), RMS, rate, spectral flatness | | ⬜ | unit tests on synthetic tones |
| P2b.2 | Speaker baselines + z-scores (§5.9.2) | | ⬜ | |
| P2b.3 | LLM emotion labelling with ±2 lines of context → `{emotion, intensity, nonverbal, position}` | | ⬜ | sample output |
| P2b.4 | Fusion rule (milder label on disagreement) + 2-segment smoothing | | ⬜ | unit tests |
| P2b.5 | Hand-label the expressive clip (≈30 segments) | | ⬜ | `samples/labels.json` |
| P2b.6 | Detection accuracy on the expressive clip; target **≥ 70%** agreement | | ⬜ | % |
| P2b.7 | Emotion → controls mapping (§5.9.3), with per-language fallbacks from P0.9 | | ⬜ | |
| P2b.8 | Tags placed by the LLM inside translations; at most 1 nonverbal tag unless the source had more (C18) | | ⬜ | |
| P2b.9 | 💳 Dub the expressive clip; check laugh/shout/whisper lines by ear | | ⬜ | recording |

---

## P3: Assemble / mix / mux (Oct 19–21)

| ID | Task | Owner | Status | Evidence |
|---|---|---|---|---|
| P3.1 | Timeline at 48 kHz, exact length, absolute placement, 10 ms fades (§5.6) | | ⬜ | unit test: length = video length |
| P3.2 | Loudness normalisation −16 LUFS (two-pass `loudnorm`) | | ⬜ | measured LUFS |
| P3.3 | Duck mode (`sidechaincompress`) and mute mode | | ⬜ | A/B by ear |
| P3.4 | Mux with `-c:v copy`, AAC 192k, exact duration | | ⬜ | ffprobe in vs out |
| P3.5 | SRT export (source + target) | | ⬜ | opens in VLC, in sync |
| P3.6 | Sync check script: start offsets, overruns, output duration error | | ⬜ | report |
| P3.7 | Exit: **output duration error = 0 samples** on all test clips | | ⬜ | numbers |

---

## P4: Frontend (Oct 22–28)

| ID | Task | Owner | Status | Evidence |
|---|---|---|---|---|
| P4.1 | React + Vite scaffold, design tokens, layout (desktop + 375 px phone) | | ✅ | `frontend/`; Apple-style dark; 0 px overflow on every step at 375 px (headless check) |
| P4.2 | Upload with drag-drop, size/length checks and clear errors | | ✅ | ≤ 500 MB, ≤ 10 min, video types; upload progress via XHR |
| P4.3 | Language pickers (source, target) | | ✅ | 10 sources + auto; 11 targets incl. Hinglish |
| P4.4 | Transcript editor on a segment timeline; play per segment | | ✅ | editable lines, follow-playback, captions on video |
| P4.5 | Emotion chips with override (F14) | | ✅ | 8 emotions, intensity + nonverbal tags shown |
| P4.6 | Voice picker: persona grid filtered by language and gender, previews | | ✅ | real 42-voice catalogue; previews call `/api/voices/{id}/preview` (live only, untested) |
| P4.6b | Voice clone: from the video (auto-picked stretch), uploaded sample, or mic recording; 5–30 s check; consent gate | | ✅ | recording captured 6.4 s in headless test; sent as multipart `voice_sample` |
| P4.7 | Live progress per stage (SSE) | | ✅ | demo-mode simulated; real `EventSource` client written, untested |
| P4.8 | Flagged-segment list + per-segment regenerate | | ✅ | demo |
| P4.9 | A/B player (original ↔ dubbed) | | ✅ | demo returns the original video for both |
| P4.10 | Downloads (MP4, SRTs) + project history | | ✅ | SRTs generated client-side in demo |
| P4.11 | Exit: full flow end to end against the **real backend** | | ⬜ | blocked on P1 |

---

## P5: Voice clone (Oct 25–28)

| ID | Task | Owner | Status | Evidence |
|---|---|---|---|---|
| P5.1 | Automatic reference pick: cleanest 5–30 s of the speaker; user can adjust | | ⬜ | |
| P5.2 | Consent gate (checkbox + stored record) | | ⬜ | |
| P5.3 | 💳 Embedding call + per-job cache | | ⬜ | |
| P5.4 | Clone TTS path through the same fit engine | | ⬜ | |
| P5.5 | "AI-generated voice" label in the UI + file metadata | | ⬜ | ffprobe metadata |
| P5.6 | 💳 Dub clip 1 in a team member's cloned voice into 2 languages | | ⬜ | recording |

---

## P6: Quality & evaluation (Oct 29–Nov 4)

| ID | Task | Owner | Status | Evidence |
|---|---|---|---|---|
| P6.1 | Pick 5 demo clips (synthetic or self-recorded) covering calm, expressive, noisy and code-mixed speech | | ⬜ | |
| P6.2 | 💳 Dub all 5 into the demo languages (credit-checked first) | | ⬜ | |
| P6.3 | Sync metrics: overrun %, stretch p50/p95, duration error | | ⬜ | table |
| P6.4 | Translation adequacy: bilingual rater, 20 segments, 1–5 | | ⬜ | mean |
| P6.5 | Naturalness: 5 listeners, fit engine vs baseline | | ⬜ | means |
| P6.6 | Emotion transfer match % + blind A/B vs a flat dub | | ⬜ | % |
| P6.7 | Credits per video minute | | ⬜ | number |
| P6.8 | Fix the 3 worst failure modes found | | ⬜ | before/after |
| P6.9 | Processing time vs video length (N3) | | ⬜ | ratio |

## v2: Multi-speaker (stretch, Nov 1–4, only if P6 is on track)

| ID | Task | Status | Evidence |
|---|---|---|---|
| V2.1 | 💳 Batch STT with `with_diarization` + `num_speakers` | ⬜ | |
| V2.2 | Per-speaker voice mapping UI + persona suggestion (§5.9.4) | ⬜ | |
| V2.3 | Per-speaker baselines in the emotion stage | ⬜ | |
| V2.4 | 💳 Two-speaker demo clip | ⬜ | |

---

## P7: Submission (Nov 5–9)

| ID | Task | Owner | Status | Evidence |
|---|---|---|---|---|
| P7.1 | Freeze features (Nov 5) | | ⬜ | |
| P7.2 | 60 s demo video: one clip → 3 languages, including the emotion moment and the sync guarantee | | ⬜ | file |
| P7.3 | Written explanation: problem, users, architecture, measured results, limits | | ⬜ | doc |
| P7.4 | Model list + each member's contribution | | ⬜ | |
| P7.5 | README setup verified from a clean clone by a teammate | | ⬜ | |
| P7.6 | LinkedIn/X post with #GreatIndianAIInternshipChallenge #GnaniAI | | ⬜ | link |
| P7.7 | Data check: no real personal identifiers or third-party voices anywhere | | ⬜ | checklist |
| P7.8 | **Submit on Nov 9** | | ⬜ | confirmation |

---

## Credit ledger (5,000 per registrant)

| Date | Task | Calls | Credits used | Running total | Notes |
|---|---|---|---|---|---|
| | | | | 0 | |

Per-call costs (fill in after P0.14): Batch STT per minute = ? · TTS per call = ? · Clone embedding = ? · Clone TTS = ?

**Rule:** no 💳 task over 50 credits runs without checking this ledger first.

---

## Risk watch

| Risk | Trigger | Fallback | Owner |
|---|---|---|---|
| Organisers rule Gnani-only | D1 answer | Swap the interface to Evon via an organiser endpoint / Inya agent / self-host (PLAN §4.3) | |
| Tags don't work in target languages | P0.9 shows no effect | Speed + punctuation only for those languages; demo emotion in the languages where tags work | |
| Credits run low | Ledger > 3,500 before P6 | Shorter demo clips, fewer languages, reuse the cache | |
| Fit quality poor | P2.10 fails | More `short` variants, a lower budget factor, accept up to 1.3× with flags | |
| Frontend late | P4.11 not done by Oct 28 | Cut the waveform editor to a simple list editor | |

---

## Log

| Date | Who | What happened | Next |
|---|---|---|---|
| Oct 8 | | Pivoted from Samvedna to video dubbing; PLAN.md, README.md and this tracker written; emotion transfer added to the plan; git set up for mithra009/vani | P0.3 pull + merge, P0.4 Discord questions, P0.5 record test clips |
| Oct 8 | | Decided: Gemini 3.5 Flash-Lite as the interim LLM (D1); Evon hosting deferred (D5) | Add `GOOGLE_API_KEY` to `.env` |
| Oct 8 | | Narrate mode added to the frontend (record over video, keep own voice or re-voice). Backend built in `backend/` (FastAPI, SQLite, Gnani/Gemini/fake providers, fit engine, emotion, ffmpeg assembly). Tests with fake providers: unit 20/20 alone, e2e 6/6 alone; **running both files in one pytest session times out (unresolved)**. No real Gnani/Gemini call made yet | Fix combined-suite hang; then the paid pilot (P0.6+) |
| Oct 8 | | Frontend built (P4.1–P4.10) with demo mode + voice-clone sources; full flow passes headless at 1440 px and 375 px, no page errors | P1 backend to match the API contract in `frontend/src/lib/api.js` |
