# Video Voice-Over Studio: Plan

*Working title. Rename freely.*

A web app where a user uploads a video and gets it back **dubbed into another Indian language**. They pick either one of Gnani's 42 Timbre voices or a clone of the original speaker's voice. Each dubbed line starts exactly when the original line started, and the output has exactly the same length as the input.

Built for the **Great Indian AI Internship Challenge 2026** (deadline **10 Nov 2026, 11:59 PM IST**) under its rule *"Use Gnani AI models/APIs only."*

---

## 1. What "perfect sync, no delay" means here

Dubbing is an **offline job**. The user uploads, waits a few minutes and gets a file back, so "no delay" can't mean real-time output. It means **no drift**:

| Guarantee | Target | How |
|---|---|---|
| Each dubbed line **starts** at the original line's timestamp | ±20 ms (we place the audio by sample index, so it's exact by construction) | Timeline assembly (§5.6) |
| Each dubbed line **ends** within its slot | ≥ 95% of lines with no overrun; rest flagged in the UI | Fit loop (§5.4–5.5) |
| Output length = input video length | Exact, to the audio sample | Pad or trim the final track, then mux |
| No cumulative drift over long videos | 0: every line is anchored to its own timestamp, never to the end of the previous line | Absolute placement |
| Lip sync | **Out of scope** | It needs a non-Gnani video model, which the rules don't allow |

Put this table in the demo. It shows the judges exactly what we claim.

---

## 2. Scope

### v1: the hackathon build
- Upload one video (MP4/MOV/WebM/MKV), **≤ 10 minutes**.
- Source speech in any Prisma language: hi, en, bn, gu, kn, ml, mr, pa, ta, te, or code-mixed Hinglish.
- Target in any Timbre v2.5 language: the same 10, plus Hinglish (`hi-en`).
- Voice options:
  - **Persona:** one of 42 Timbre v2.5 voices, filtered by target language and gender, with preview clips.
  - **Clone:** the original speaker's voice, made from a 5–30 s clean excerpt after an explicit consent checkbox.
- **Editable transcript and translation** before synthesis. Users fix recognition and translation errors, which is also our quality safety net.
- Background audio: **duck** the original track under the dub (default), or **mute** it.
- Download the dubbed MP4, plus SRT subtitles in both languages.

### v2: stretch goals, only if v1 is solid
- **Multiple speakers:** diarization tells speakers apart, each gets their own voice.
- Several target languages from one upload.
- Pacing tags (`<slow>`, `<rushed>`, `<pauses>`) used deliberately for expressive lines.

### Not doing
- Lip sync.
- Separating music from voice with a non-Gnani model like Demucs (rules risk; §7 C8).
- Real-time or live dubbing.
- Translating into languages outside Timbre's list. "Any language" means the 10 Indic languages plus Hinglish.

---

## 3. Requirements

### 3.1 Functional

| ID | Requirement |
|---|---|
| F1 | Upload a video ≤ 10 min / ≤ 500 MB; reject anything without an audio track, with a clear message |
| F2 | Extract the audio and transcribe it with **timestamped segments** (Prisma Batch STT) |
| F3 | Show the transcript as editable segments on a timeline, with original audio playback per segment |
| F4 | Translate each segment to the target language **within a length budget** that fits its time slot (Evon v3.3) |
| F5 | Let the user pick a persona (with preview) or clone the speaker's voice (with consent) |
| F6 | Synthesise each segment (Timbre v2.5 or a voice clone) and fit it to its slot |
| F7 | Assemble a dub track exactly as long as the video, mix it with the original audio (ducked or muted) and mux it into an MP4 |
| F8 | Show job progress per stage; flag segments that couldn't be fitted cleanly; allow per-segment regenerate |
| F9 | Side-by-side or A/B player: original vs dubbed |
| F10 | Download the MP4 and SRTs; keep a job history |
| F11 | Cache every paid API result by content hash, so re-runs and edits never pay twice |

### 3.2 Non-functional

| ID | Requirement |
|---|---|
| N1 | Sync guarantees in §1 |
| N2 | Credits: the whole demo set fits inside the **5,000 build credits** per registrant (§8) |
| N3 | Processing time ≤ 2× video length for a 3-minute video (a target, to measure) |
| N4 | **Synthetic data only:** no real phone, account, Aadhaar or PAN numbers and no real people's voices without consent. Demo videos are self-recorded. |
| N5 | Runs on one laptop, plus a GPU box for Evon if needed (§4.3) |
| N6 | Every stage is resumable: a failed job restarts from the last completed stage |

### 3.3 Accounts, tools and hardware

| Need | Detail |
|---|---|
| Gnani API key | `GNANI_API_KEY` (already in `.env`), used for STT, TTS and voice cloning |
| Evon v3.3 weights | Request access on Hugging Face (Apache 2.0). **No hosted endpoint in Gnani's public docs**, so we host it ourselves |
| GPU for Evon | 30B MoE with about 3.5B parameters active. A 4-bit build should fit about 18–20 GB of VRAM, so one 24 GB GPU (cloud A10G/L4/4090), **still to be verified** (§7 C1) |
| ffmpeg | 6.x on PATH (audio extraction, time-stretch, loudness, muxing) |
| Python 3.12 | Already in `.venv` |
| Node 20+ | Already installed (v22) |
| Public file URL (optional) | Batch STT accepts direct uploads ≤ 10 MB. Longer audio either goes as compressed audio, which fits for v1 lengths (§5.2), or through a public HTTPS URL |

---

## 4. System architecture

```
 Browser (React + Vite)
   upload ─┐   transcript editor   voice picker   progress   A/B player   download
           ▼          ▲                  ▲            ▲(SSE)
 ┌──────────────────────── FastAPI backend ─────────────────────────────┐
 │ REST: /jobs  /jobs/{id}  /jobs/{id}/segments  /voices  /preview      │
 │ SSE:  /jobs/{id}/events                                              │
 │                                                                      │
 │  Job runner (asyncio worker, one job at a time) ── SQLite (jobs,     │
 │      │                                             segments, cache)  │
 │      ▼                                                               │
 │  1 ingest ─► 2 transcribe ─► [user review] ─► 3 translate ─►         │
 │  4 synthesise+fit ─► 5 assemble ─► 6 mix+mux ─► done                 │
 │      │           │                    │             │                │
 └──────┼───────────┼────────────────────┼─────────────┼────────────────┘
        ▼           ▼                    ▼             ▼
     ffmpeg   Gnani Prisma        Evon v3.3 (self-   Gnani Timbre v2.5 /
              Batch STT           hosted, OpenAI-    Voice-clone TTS
              (segments,          compatible server)
              diarization)
                                              storage/: uploads, audio, segments, outputs
```

### 4.1 Components

| Component | Tech | Responsibility |
|---|---|---|
| Frontend | React + Vite + Framer Motion | Upload, transcript/translation editor on a waveform timeline, voice picker with previews, live progress, A/B player |
| API server | **FastAPI** + Uvicorn | Job CRUD, file upload/download, SSE progress, voice catalogue |
| Job runner | asyncio task queue inside the API process | Runs pipeline stages; each stage is idempotent and checkpointed in SQLite |
| Store | SQLite + local `storage/` folder | Jobs, segments, per-segment artefacts, API-result cache |
| Media | ffmpeg (subprocess) + numpy + soundfile | Extract, resample, trim silence, time-stretch, assemble, loudness, mux |
| STT | Gnani **Prisma v2.5 Batch** | Segment timestamps, optional diarization, ITN off (`verbatim`) for translation fidelity |
| Translation | **Evon v3.3** behind vLLM or llama.cpp (OpenAI-compatible API) | Length-budgeted translation, per-segment JSON in and out |
| TTS | Gnani **Timbre v2.5** REST (personas) / **Voice-clone TTS** REST (clone) | Synthesis with `speed` 0.85–1.15 and pacing/pause tags |

### 4.2 Why these choices
- **Batch STT, not the realtime socket.** It returns segment `start_time`/`end_time` and speaker IDs, which is exactly the skeleton a dub needs. Realtime gives text only.
- **REST TTS, not WebSocket.** It's offline, segments are independent, and REST is simpler to retry and cache.
- **Absolute timestamp placement.** Each line is placed at its own start time, so one long line can never push later lines out of sync.
- **Human review step.** Recognition and translation errors are the biggest quality risk. A 30-second skim-and-fix beats any automatic heuristic, and it demos well.

### 4.3 Evon hosting options (decide in Week 1)
1. **Cloud GPU** (L4/A10G 24 GB) with vLLM or llama.cpp serving a 4-bit build. This is the best quality per unit of effort.
2. **CPU with llama.cpp** using a GGUF build, if one exists. Only about 3.5B parameters are active per token, so it may be usable on a laptop CPU. Slow but free.
3. **Ask the organisers** (Discord) whether a hosted Evon endpoint exists for participants.

---

## 5. The pipeline in detail

### 5.1 Ingest
- `ffprobe` gives duration, audio streams, frame rate. Reject videos with no audio or longer than 10 minutes.
- `ffmpeg -ac 1 -ar 16000` makes a mono 16 kHz WAV for STT. A 48 kHz copy of the original audio is kept for mixing.

### 5.2 Transcribe (Prisma Batch STT)
- Upload compressed audio (Opus or MP3 around 32 kbps: 10 min is about 2.4 MB, which fits the 10 MB direct-upload limit).
- Config:
  - `model: gnani-prisma-v2.5`
  - `language_code`: the user's choice, or up to 3 codes for auto-detection
  - `with_diarization`: on in v2
  - `with_denoise: true` for noisy clips
- Create the job, then start it, then poll until it finishes.
- Result: `segments[{start_time, end_time, text, speaker_id?}]`.
- **Normalise segments.** Merge segments shorter than 1.2 s into their neighbours when the gap is under 300 ms. Split anything over 12 s at the largest internal pause, which we find with an energy-based silence detector, not a model.
- Each segment's *slot* is `[start, next_start − 120 ms]`. The 120 ms keeps a breath of silence between lines.

### 5.3 Review (user)
- The editor shows segments on the timeline. The user fixes the text and, optionally, marks lines as "keep original", for names or songs.

### 5.4 Translate with a length budget (Evon)
- **Calibrate once per voice:** synthesise one fixed paragraph per target voice to measure its **characters per second** at `speed=1.0`, then cache it. This costs about one TTS call per voice, ever.
- **Budget:** `max_chars = slot_seconds × chars_per_sec × 0.95`.
- **One Evon call per batch of about 20 segments**, as JSON with a few lines of context around each segment. Each segment asks for two variants:
  - `natural`: a faithful translation.
  - `short`: the same meaning at ≤ 80% of the budget.
- Prompt rules:
  - Keep names, numbers and brand words.
  - Use spoken, not written, register.
  - Return Hinglish only if the target is `hi-en`.
- Choose `natural` if its predicted duration fits, otherwise `short`.

### 5.5 Synthesise and fit (Timbre / voice clone)
For each segment:
1. Predict the duration from text length and the voice's characters per second, then set `speed = clamp(predicted / slot, 0.85, 1.15)`.
2. Call the TTS. **Cache it by hash** of (text, voice, speed, language).
3. Trim leading and trailing silence (threshold −45 dBFS) and measure the real duration `A`.
4. Fit:
   - `A ≤ slot`: place as-is. The rest of the slot stays as natural silence.
   - `slot < A ≤ 1.15 × slot`: time-stretch with **ffmpeg `atempo`**, which keeps pitch.
   - `A > 1.15 × slot`: switch to the `short` variant and re-synthesise (**at most 1 retry**). If it still overruns, borrow up to 300 ms from the following gap, otherwise stretch up to 1.25× and **flag** it in the UI.
   - The combined `speed` × `atempo` is capped at about 1.3× real-time, because beyond that it sounds rushed.
5. If the segment is much shorter than its slot, which happens in English to Hindi, leave it aligned at the start. Don't slow it below 0.85×, because slow speech sounds unnatural.

### 5.6 Assemble
- Build a float32 timeline at 48 kHz, exactly `round(video_duration × 48000)` samples long.
- Write each fitted segment at `round(start × 48000)` with 10 ms fades.
- Normalise loudness to −16 LUFS integrated (ffmpeg `loudnorm`, two passes).

### 5.7 Mix and mux
- **Duck mode:** `sidechaincompress` lowers the original audio by about 15 dB wherever the dub is speaking. Music and effects survive between lines.
- **Mute mode:** dub only.
- Mux with `ffmpeg -c:v copy` so the video isn't re-encoded and frames can't shift, with audio as AAC 192k. Audio is padded or trimmed to the exact video duration.
- Write SRTs from the segments in the original and target languages.

### 5.8 Voice clone path
- Pick the cleanest 5–30 s of the original speaker. The automatic default is the longest run of segments with the lowest background energy; the user can change it.
- `POST /api/v1/tts/voice-clone/embeddings` returns a 768-dim embedding, which we cache per job.
- Clone TTS: `POST /api/v1/tts/inference` with `speaker_embedding`.
- **Consent gate:** a checkbox stating the user owns the voice or has the speaker's permission. Clone outputs carry an "AI-generated voice" tag in the file metadata and in the UI.

---

## 6. Data model (SQLite)

```
jobs(id, status, stage, video_path, duration_s, src_lang, tgt_lang, voice_mode, voice_id,
     clone_embedding_path, bg_mode, created_at, error)
segments(id, job_id, idx, start_s, end_s, slot_end_s, speaker, src_text, tgt_text_natural,
         tgt_text_short, chosen_variant, speed, stretch, tts_path, actual_s, flags)
cache(key_sha256, kind, path_or_json, created_at)      -- STT / translation / TTS results
voice_calibration(voice_id, lang, chars_per_sec)
```

API:

| Method | Path | Purpose |
|---|---|---|
| POST | `/jobs` | Upload a video and create a job (runs ingest and transcribe) |
| GET | `/jobs/{id}` | Status, stage, metadata |
| GET/PATCH | `/jobs/{id}/segments` | Read or edit transcript, translation, keep-original flags |
| POST | `/jobs/{id}/dub` | Start translate, synthesise, assemble and mux with the chosen voice settings |
| POST | `/jobs/{id}/segments/{idx}/regenerate` | Redo one segment |
| GET | `/jobs/{id}/events` | Server-sent progress events |
| GET | `/voices?lang=` | Persona catalogue with preview URLs |
| GET | `/jobs/{id}/output.mp4`, `/subs.{lang}.srt` | Downloads |

---

## 7. Challenges and mitigations

| # | Challenge | Why it's hard | Mitigation |
|---|---|---|---|
| C1 | **Hosting Evon** | No hosted endpoint, and a 30B MoE needs a GPU | Decide in week 1 (§4.3); ask on Discord; keep the translator behind one interface so the backend can be swapped |
| C2 | **Length mismatch between languages** | Hindi and Tamil often run 15–40% longer than English for the same meaning | Budgeted translation with a `short` variant, speed 0.85–1.15, `atempo` ≤ 1.15, borrowing from gaps, flagging the rest |
| C3 | **Gnani's speed range is narrow** (0.85–1.15) | It can't absorb big mismatches alone | Combine with pitch-preserving `atempo`, capped at about 1.3× total so it doesn't sound rushed |
| C4 | **Segment timestamps are coarse** | Batch STT gives segment-level, not word-level, timing | Treat segments as slots; split long ones at energy pauses; don't promise word-level sync |
| C5 | **Recognition and translation errors** | Names, numbers, code-mixing | Word boosting via `bias_list`; ITN off; the user edits before dubbing; Evon keeps names and numbers |
| C6 | **TTS padding and silence** | Leading and trailing silence distort the duration | Trim before measuring and fitting |
| C7 | **Credit budget (5,000)** | Every retry and preview costs | Content-hash cache; at most 1 retry per segment; previews cached once per voice; a 60-second pilot before full runs; check per-call cost in the dashboard after the pilot |
| C8 | **Keeping background music** | Removing only the voice needs source separation (a non-Gnani model, so a rules risk) | Default to ducking; mute as an option; ask on Discord before adding Demucs |
| C9 | **Multiple speakers** | Each needs its own voice; diarization errors swap voices | v1 is single-speaker; v2 uses `with_diarization` + `num_speakers` with per-speaker voice mapping the user can fix |
| C10 | **Voice-clone misuse** | Deepfake risk | Consent gate, AI-voice labelling, own or synthetic voices only (also a hackathon rule) |
| C11 | **Upload limits** | Batch direct upload ≤ 10 MB | Compress to low-bitrate Opus before upload; a public URL for longer files |
| C12 | **Rate limits (429)** | Bursts of TTS calls | Concurrency of 3 with exponential backoff and jitter |
| C13 | **Language coverage mismatch** | Gnani docs disagree on whether Batch STT covers Gujarati and Punjabi | Test early; fall back to REST STT in ≤ 30 s chunks for those languages |

---

## 8. Credit budget (estimate, check after the pilot)

Per-call credit costs aren't in the docs. Run the 60-second pilot, read the usage in the dashboard, then fill in this table:

| Item | Calls for a 3-min video (~35 segments) | Credits/call | Total |
|---|---|---|---|
| Batch STT | 1 job (3 min audio) | ? | ? |
| Voice calibration | 1 per voice used (cached forever) | ? | ? |
| TTS | ~35 + ~5 retries | ? | ? |
| Voice-clone embedding | 1 per job | ? | ? |

Rule: **no full-length run until the pilot numbers are in.**

---

## 9. Roadmap and checkpoints (Oct 8 to Nov 10)

| Week | Phase | Done when (evidence) |
|---|---|---|
| **W1** (Oct 8–14) | P0: verify APIs + Evon hosting | Batch STT returns segments for a 60 s self-recorded clip; one Timbre call per target language; voice-clone embedding works on a 15 s self-recording; Evon translates 10 sentences on our chosen host |
| | P1: backend skeleton | FastAPI + SQLite + job runner; ingest + transcribe stages pass on the pilot clip |
| **W2** (Oct 15–21) | P2: translate + fit engine | Unit tests for slot computation, the fit decision and assembly; the pilot dub has **0 overruns > 1.25×** and output duration exactly equal to the input |
| | P3: assemble/mix/mux | Duck and mute modes; A/B by ear; the SRT opens in VLC in sync |
| **W3** (Oct 22–28) | P4: frontend | Upload → review → voice pick → progress → A/B player → download, end to end |
| | P5: voice clone | Clone path with consent gate on a team member's voice |
| **W4** (Oct 29–Nov 4) | P6: quality + evaluation | Metrics on 5 demo clips (§10); fix the worst failure modes |
| | v2 stretch | Multi-speaker diarization, *if* P0–P6 are green |
| **Final** (Nov 5–10) | P7: submission | 60 s demo video, write-up naming Prisma v2.5, Timbre v2.5, voice-clone TTS and Evon v3.3, LinkedIn/X post with both hashtags. **Submit by Nov 9**, a day early |

---

## 10. How we'll measure it

| Metric | How |
|---|---|
| Start-time offset per segment | Placement index vs STT start (should be about 0; it's a sanity check) |
| Overrun rate | % of segments where fitted duration > slot |
| Stretch distribution | Median and p95 of speed × atempo |
| Output duration error | `|out − in|`, which must be 0 samples after the mux re-probe |
| Translation adequacy | A bilingual teammate rates 20 random segments 1–5 |
| Naturalness | 5 listeners rate dubbed clips 1–5, with and without the fit engine (fixed 1.0 speed and hard truncation as the baseline) |
| Credits per video minute | Dashboard usage ÷ minutes processed |

---

## 11. Award fit

- **Main Character:** dub into regional languages, e.g. Tamil, Kannada, Bengali.
- **Mixed Vibes:** Hinglish (`hi-en`) source and target.
- **Demo Day Drop:** a dubbing tool *is* a video demo. Show the same clip in 3 languages in 60 seconds.
- **Jugaad Genius:** voice-cloned dubbing for creators and teachers. One lecture recorded once can reach students in 10 languages in the teacher's own voice.

---

## 12. Open questions

1. Must translation use Evon, or is another LLM allowed? Is there a hosted Evon endpoint? **(Ask on Discord.)**
2. Is a non-Gnani source-separation model like Demucs allowed for keeping music? **(Ask on Discord.)**
3. Which source/target languages do we demo? This needs someone who can judge the target-language quality.
4. Team: solo or two people? It affects the award category and how the work is split.
