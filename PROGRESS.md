# Vani: Progress Tracker

Organised by the components in [High_level_design.png](High_level_design.png). Pipeline details are in [PLAN.md](PLAN.md) (§ refers to it).
**Deadline: 10 Nov 2026, 11:59 PM IST. Target: submit on 9 Nov.** Last updated: 10 Oct.

**How to read this**
- ✅ done (evidence exists) · 🟨 partly done or done but not verified live · ⬜ not started · ⛔ blocked · ➖ dropped
- "Verified" means seen working: a passing test, a measured result or a confirmed run. Code that exists but hasn't been seen working is 🟨.
- 💳 = spends Gnani or Gemini credits.

---

## Dashboard

```
 Authentication  ──►  Landing page  ──►  Rate limiting  ──►  Media · Project/Editor · Export services  ──►  Supabase DB
      🟨 5/7             ✅ 6/6             ⬜ 0/2              🟨 3/8 · 🟨 13/27 · 🟨 2/6                     🟨 5/7
```

| Component | Status | Done / total | What's left |
|---|---|---|---|
| 1. Authentication | 🟨 | 5 / 7 | OTP on signup, forgot password |
| 2. Landing page | ✅ | 6 / 6 | none |
| 3. Rate limiting + Redis queue | ⬜ | 0 / 2 | both |
| 4. Media service (uploads, library) | 🟨 | 3 / 8 | Library API, Supabase Storage, live check of upload rows |
| 5. Project service | 🟨 | 4 / 7 | rename/delete endpoints, live check |
| 6. Editor service (the AI pipeline) | 🟨 | 9 / 20 | **real Gnani/Gemini pilot**, emotion experiments, quality evaluation |
| 7. Export service | 🟨 | 2 / 6 | multiple formats, resolutions, exports table |
| 8. Supabase DB | 🟨 | 5 / 7 | exports table, Storage bucket |
| 9. Quality, tests, submission | 🟨 | 3 / 12 | e2e test failure, evaluation, demo video, submission |

**Overall: 37 / 75 done (✅ only).** **Critical path now:** the paid pilot (E1). Nothing in the AI pipeline has run against the real Gnani or Gemini APIs yet. Everything after it depends on the pilot's results.

---

## 1. Authentication

| ID | Task | Status | Evidence |
|---|---|---|---|
| A1 | Sign-up: username (slug), first name, last name, email, password, all mandatory | ✅ | `backend/app/auth.py`, `pages/AuthPage.jsx`; confirmed working by Mithravardhan on 10 Oct |
| A2 | Sign-in with username **or** email + password | ✅ | `/api/auth/signin` resolves username → email; confirmed working on 10 Oct |
| A3 | Validation: username rules, 8+ char password, unique username/email, live "username available" check | ✅ | 11/11 auth tests pass (`backend/tests/test_auth.py`) |
| A4 | Session tokens verified locally (ES256 / JWKS); every API route requires sign-in; users only see their own projects | ✅ | tests: no token → 401, forged token → 401, other user's project → 404 |
| A5 | Frontend: protected routes, profile menu (pastel avatar, sign out), sign-up fits one screen | ✅ | headless checks at 1600×750 (submit at 652 px of 750) |
| A6 | OTP email verification on signup (`*` in design) | ⬜ | accounts are currently created pre-confirmed |
| A7 | Forgot password (`*` in design) | ⬜ | |

## 2. Landing page

| ID | Task | Status | Evidence |
|---|---|---|---|
| L1 | Info about Vani: hero, animated sync timeline, feature tiles | ✅ | `pages/Landing.jsx`, `components/SyncTimeline.jsx` |
| L2 | Info about Gnani: Prisma v2.5, Timbre v2.5, voice cloning, stats | ✅ | |
| L3 | Developers: Mithravardhan P N, Arko Bera | ✅ | roles shown as "Developer" (placeholder) |
| L4 | User profile icon → profile menu | ✅ | |
| L5 | Projects section (real data) and Library section | ✅ | workspace cards; Library uses placeholder data |
| L6 | Design: ivory text, pastel blue, no horizontal scroll at 390–1440 px | ✅ | headless screenshots, 0 px overflow |

## 3. Rate limiting + message queue

| ID | Task | Status | Evidence |
|---|---|---|---|
| R1 | Rate limiting per user / IP on the API | ⬜ | |
| R2 | Redis message queue between the API and the workers | ⬜ | currently an in-process asyncio worker, one job at a time (`backend/app/jobs.py`) |

## 4. Media service

| ID | Task | Status | Evidence |
|---|---|---|---|
| M1 | Upload a video with a project; checks: video stream, ≤ 10 min, ≤ 500 MB | ✅ | e2e test `test_dub_persona_end_to_end`, `test_rejections` |
| M2 | Store video + metadata (duration, size) and write an `uploads` row | 🟨 | code done; files on local disk (`storage/`); `uploads` insert not yet seen working in Supabase |
| M3 | Narration and voice-sample uploads recorded as `uploads` rows | 🟨 | code done, not seen live |
| M4 | Library page UI: grid, search, drag-drop upload, "New project" from a video | ✅ | placeholder data + session uploads (`lib/libraryStore.js`) |
| M5 | New project picks from the Library (two slides, optional name defaulting to video name) | ✅ | headless flow test, 10 Oct |
| M6 | Library API (`GET/POST/DELETE /api/library`) backed by the `uploads` table | ⬜ | deferred by request |
| M7 | Supabase Storage bucket for videos (free-plan file-size limits need checking) | ⬜ | |
| M8 | Library survives page refresh (needs M6) | ⬜ | |

## 5. Project service

| ID | Task | Status | Evidence |
|---|---|---|---|
| P1 | Create a project (dub or narrate) with optional name | ✅ | e2e tests; `name` field added 10 Oct |
| P2 | List projects (own only), search and filters in UI | ✅ | auth tests + Projects page |
| P3 | Progress state stored in `projects` table (write-behind, ≤ 2 writes/s) | 🟨 | code done; not yet seen live in Supabase |
| P4 | Open a project → Vani editor page | ✅ | |
| P5 | Rename project (`PATCH /api/jobs/{id}`) | 🟨 | UI done; **backend endpoint not built** (deferred) |
| P6 | Delete project (`DELETE /api/jobs/{id}`) + its files | 🟨 | UI with confirmation done; **backend endpoint not built** (deferred) |
| P7 | Resume interrupted projects after a restart | ✅ | `lifespan` re-queues; cached paid calls make it free |

## 6. Editor service (the AI pipeline)

| ID | Task | Status | Evidence |
|---|---|---|---|
| E1 | 💳 **Paid pilot**: one 60 s self-recorded clip through real Gnani STT/TTS + Gemini | ⬜ | **not run**; the request formats follow Gnani's docs but haven't been checked against the live API |
| E2 | Batch STT client (create → start → poll → transcript) | 🟨 | written to the docs; fake-provider tests only |
| E3 | Segment normalising, slots, timing fit engine (speed, atempo, short retry, borrow, flag) | ✅ | 20/20 unit tests |
| E4 | Length-budgeted translation (Gemini 3.5 Flash-Lite, JSON schema) | 🟨 | written; not called live |
| E5 | Emotion: acoustic features + LLM label + fusion + smoothing → Timbre tags/speed | 🟨 | unit-tested logic; LLM part not called live |
| E6 | 💳 Emotion experiments: do tags work per language, tag durations, clone emotion (PLAN §5.9.5) | ⬜ | |
| E7 | TTS with 42 Timbre voices; voice previews | 🟨 | written; not called live |
| E8 | Voice clone: from video, uploaded sample, or mic recording; consent gate | 🟨 | fake-provider e2e test; not called live |
| E9 | Narrate mode: record over video, keep own voice or re-voice | ✅ | e2e `test_narrate_own_voice` + headless UI test |
| E10 | Transcript review UI: edit lines, emotion override, keep original | ✅ | |
| E11 | Voice step UI: personas by language/gender, clone sources, background mode | ✅ | |
| E12 | Live progress over SSE | ✅ | |
| E13 | Assembly: sample-exact placement, loudness, duck/mute mix, video stream copied | ✅ | e2e: output length within 0.05 s, lines start at original timestamps |
| E14 | Subtitles (SRT) for both languages | ✅ | e2e test |
| E15 | Regenerate a flagged line | 🟨 | written; not tested |
| E16 | Free development mode (`FAKE_PROVIDERS=1`) | ✅ | used by all tests |
| E17 | Result page: A/B player, timing report, downloads | ✅ | |
| E18 | Multi-speaker (diarization → voice per speaker) | ⬜ | stretch |
| E19 | Switch translation to Evon if organisers require Gnani-only (D1) | ➖ | only if D1 says so |
| E20 | Quality evaluation: overrun %, translation rating, listener tests (PLAN §10) | ⬜ | needs E1 |

## 7. Export service

| ID | Task | Status | Evidence |
|---|---|---|---|
| X1 | Render the dubbed video (MP4, original resolution, video stream untouched) | ✅ | e2e test |
| X2 | Download MP4 + SRTs from the result page | ✅ | |
| X3 | Export to multiple formats (e.g. WebM, MOV, audio-only) | ⬜ | |
| X4 | Export to multiple resolutions (1080p / 720p / 480p) | ⬜ | |
| X5 | `exports` table: one row per export | ⬜ | |
| X6 | Export history per project | ⬜ | |

## 8. Supabase DB

| ID | Task | Status | Evidence |
|---|---|---|---|
| D1 | `users` table linked to Supabase Auth | ✅ | migration 001; sign-up confirmed working |
| D2 | `uploads` table (the design's "Library table") | ✅ | migration 001 run |
| D3 | `projects` table with progress state (`data` jsonb) | ✅ | migration 001 run |
| D4 | Row-level security: own rows only | ✅ | policies in migration 001 |
| D5 | Backend uses the secret key server-side only; public key only in the browser | ✅ | secret key confirmed absent from the built bundle |
| D6 | `exports` table | ⬜ | |
| D7 | Storage bucket + policies | ⬜ | see M7 |

## 9. Quality, tests, submission

| ID | Task | Status | Evidence |
|---|---|---|---|
| Q1 | Unit tests | ✅ | 20/20 |
| Q2 | Auth/ownership tests | ✅ | 11/11 |
| Q3 | End-to-end tests (fake providers, real ffmpeg) | 🟨 | **5/6**: `test_clone_from_uploaded_sample` fails after the auth changes; not investigated yet |
| Q4 | Git: repo at github.com/mithra009/vani, remote merged | ✅ | merge commit `366b88f` |
| Q5 | Post D1 (Gemini allowed?) and D2 (Demucs allowed?) on the hackathon Discord | ⬜ | |
| Q6 | Record synthetic test clips (calm, expressive, noisy), self-recorded with consent | ⬜ | |
| Q7 | 5 demo clips dubbed into the demo languages | ⬜ | needs E1 |
| Q8 | Rate-limit and abuse checks | ⬜ | needs R1 |
| Q9 | 60-second demo video | ⬜ | |
| Q10 | Written explanation + models used + each member's contribution | ⬜ | |
| Q11 | LinkedIn/X post with #GreatIndianAIInternshipChallenge #GnaniAI | ⬜ | |
| Q12 | Submit (target 9 Nov) | ⬜ | |

---

## Decisions & open questions

| # | Question | Status | Decision |
|---|---|---|---|
| D1 | Is Gemini allowed for translation, or must it be Gnani's Evon? | 🟨 interim | Gemini 3.5 Flash-Lite behind a swappable interface; ask on Discord |
| D2 | Is a non-Gnani music-separation model allowed? | ⬜ open | Default: lower the original audio |
| D3 | Demo languages | ⬜ open | Proposal: Hinglish/English → Hindi, Tamil, Kannada |
| D4 | Who owns which components (Mithravardhan / Arko) | ⬜ open | |
| D5 | Developer roles shown on the landing page | ⬜ open | Currently "Developer" for both |
| D6 | Video storage: Supabase Storage vs local disk (free-plan limits) | ⬜ open | Local disk for now |

## Credit ledger (5,000 per registrant)

| Date | Task | Calls | Credits used | Running total |
|---|---|---|---|---|
| | No real Gnani or Gemini calls recorded yet | | | 0 |

Per-call costs: unknown until the pilot (E1).

## Risk watch

| Risk | Trigger | Fallback |
|---|---|---|
| Real API formats differ from the docs | E1 pilot fails | Fix the client from the actual responses; tests use fakes, so only `providers/gnani.py` changes |
| Organisers rule Gnani-only | D1 answer | Swap the LLM interface to Evon |
| Supabase free-plan file limits | M7 | Keep videos on local disk, metadata in Supabase |
| Credits run low | Ledger > 3,500 before evaluation | Shorter clips, fewer languages, rely on the cache |
| Time | Export / rate limiting not done by 1 Nov | Ship MP4 export only; document rate limiting as future work |

## Log

| Date | What happened | Next |
|---|---|---|
| Oct 8 | Pivot to video dubbing; PLAN/README written; frontend built in demo mode; Narrate mode | Backend |
| Oct 8 | Backend built (FastAPI, pipeline, fit engine, emotion, ffmpeg assembly, fake providers) | Supabase |
| Oct 10 | Supabase: users/uploads/projects tables + RLS; auth (sign-up, sign-in by username/email), ownership checks | Landing |
| Oct 10 | Landing page, Library (placeholder), Projects page, profile menu; ivory + pastel design; New project as two slides from the Library; sign-up fits one screen | Fix e2e clone test; paid pilot E1; projects rename/delete endpoints |
