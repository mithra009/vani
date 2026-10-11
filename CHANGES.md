# Session changes — Library upload & processing pipeline

Date: 2026-10-10 · Branch work: `media_service/` integration debugging + hardening.

This doc records every problem found in this session, its root cause, and the fix applied or planned.

---

## Background (what was already in place)

- `media_service/` package (FastAPI on `:8020`): signed-upload endpoints, Postgres `SKIP LOCKED` job queue (`probe` → `thumbnail` → `proxy`), FFmpeg worker (`python -m media_service.worker`).
- Migrations `supabase/migrations/002_media_assets.sql` + `003_media_objects_insert_policy.sql` (applied to live DB): `assets`/`jobs` tables, RLS, `media` bucket, INSERT policy `media_objects_insert_own`.
- Frontend Library tab (`Library.jsx`, `libraryStore.js`, `api.js`, Vite proxy `/api/uploads` + `/api/assets` → `:8020`).

---

## Problem 1 — Uploads never reached Supabase; rows stuck `INITIATED`

**Symptom:** Library showed "Waiting…" forever; storage folder empty; no jobs enqueued. Two orphaned rows (`21a7dfbc…`, `b5d82b8c…`).

**Root cause:** The browser tab was running **stale pre-fix `libraryStore.js`** whose `uploadToStorage` sent a `POST` with a raw body to the signed-URL. That hits Supabase's *create-sign* endpoint (harmless `200`, stores nothing). The fixed module was served by Vite (verified by fetching it), but the open tab kept the old copy until hard refresh. Old code also never called `/uploads/:id/complete` in the observed traces (media access log showed `init` 200, then only `GET` polls — zero `complete` POSTs).

**Evidence:** `storage/logs/media.out.log` (init 200, no complete); media `.err.log` (signed-URL creation 200 against Supabase); storage listing empty.

**Fix:**
- Deleted the two orphaned `INITIATED` rows (safe: no jobs, no bytes). `db.list_assets` already hides `INITIATED` older than 1 h.
- The correct contract (already in `libraryStore.js`) is: `PUT` to the signed URL, multipart form with a `file` part, `apikey` header (publishable key), `Authorization: Bearer <user JWT>`, `x-upsert: false`; token only in the URL query. Verified end-to-end with a disposable GoTrue user (byte-identical download, cleanup).

---

## Problem 2 — No upload feedback; user refreshed mid-upload, creating more orphans

**Symptom:** A 23 MB upload showed nothing in the UI (card appears only after `/complete`), so the natural reaction was refreshing — which aborts the XHR and orphans the `INITIATED` row.

**Fix (this session):**
- `frontend/src/lib/libraryStore.js`
  - `addVideos(files, onProgress)` now reports `(fileName, phase, fraction)` with phases `init` / `upload` / `finalize`.
  - `uploadToStorage` gained `xhr.timeout = 600_000` + `ontimeout` → clear error instead of hanging silently.
- `frontend/src/pages/Library.jsx`
  - New `busy` banner: "Preparing X… → Uploading X… N% → Finalizing X…" with a progress bar. Errors still surface in the red banner.

---

## Problem 3 — Jobs stuck `RUNNING` forever after a worker restart

**Symptom:** Asset `ea56061c…` (`Vision Quality.mp4`, 23 MB, uploaded OK) stuck `PROCESSING`; all three jobs `RUNNING` with `finished_at = NULL`; worker log idle.

**Root cause:** Worker processes were killed during a duplicate-service cleanup while jobs were mid-flight. `claim_job` only picks `status IN ('PENDING','FAILED')` — there was **no reaper for orphaned `RUNNING` jobs**, so a crash/restart permanently stranded anything claimed.

**Fix:**
- `media_service/db.py`: `requeue_stale_jobs(pool, stale_seconds)` — resets `RUNNING` jobs older than the threshold back to `PENDING` (attempts preserved, `SKIP LOCKED`-safe); clears the asset task column back to `PENDING`.
- `media_service/config.py`: `WORKER_STALE_JOB_SECONDS` (default 1800 — must exceed worst-case proxy encode), `WORKER_REAP_SECONDS` (default 60).
- `media_service/worker.py`: reaps once at startup and every `WORKER_REAP_SECONDS` in the loop; logs each requeued job.
- Recovered the three live jobs via the new function (attempts preserved).

---

## Problem 4 — `ffprobe isn't installed or isn't on PATH` (post-reaper failures)

**Symptom:** After the reaper re-ran the jobs, all three failed with `ffprobe isn't installed or isn't on PATH.` (`attempts` climbed to 4/5).

**Root cause:** ffmpeg/ffprobe **are** installed (`C:\ffmpeg\bin`, on the **Machine** PATH), but the worker was launched via background `Start-Process` from a shell whose PATH had not been refreshed (`current session has ffmpeg: False`). `media.py` invoked the bare name `"ffprobe"` → `FileNotFoundError` → `MediaError` → job failure.

**Fix:**
- `media_service/config.py`: new `FFMPEG_BIN_DIR` env setting.
- `media_service/media.py`: `_binary(name)` resolver — `shutil.which()` first, then `FFMPEG_BIN_DIR`; clearer error naming the folder checked.
- `.env`: `FFMPEG_BIN_DIR=C:\ffmpeg\bin`; documented in `.envexample`.
- Verified with `PATH` forced to `System32` only: resolves `C:\ffmpeg\bin\ffprobe.exe`, `ffprobe -version` runs, rc=0.
- Reset the three jobs for `ea56061c` to `PENDING`, `attempts=0`, and the asset to `UPLOADED` so the next worker start processes it fresh (5 clean attempts).

---

## Problem 5 — Two masked bugs surfaced once ffmpeg worked (attempt 3)

**Symptom:** With ffmpeg fixed, jobs ran further and failed with two *new* errors:
- probe: `DataError: invalid input for query argument $3: {…dict…} (expected str, got dict)`
- thumbnail + proxy: `FileNotFoundError: … '23be…/thumb.jpg'` (and `…/proxy.mp4`)

**Root causes (both real code bugs, previously hidden because nothing ever got past ffprobe):**
1. **`db.py:finish_job`** — probe built `asset_values["metadata"]` as a Python dict and the UPDATE bound it straight into the `assets.metadata` **jsonb** column. asyncpg does not serialize dicts → `DataError` on every probe finish.
2. **`storage.py:upload_file`** — **arguments swapped** for supabase-py. Correct signature is `upload(destination_key, file_path, options)`; the code called `upload(local_path, key, …)`, so the client tried to *read the storage key as a local filesystem path* → `FileNotFoundError` on every thumbnail/proxy upload. (ffmpeg had created the local file fine — the upload call never used it.)

**Fix:**
- `db.py:finish_job`: JSON-serialize any dict/list values (`json.dumps`) before binding — generic, covers `metadata` and any future jsonb column.
- `storage.py:upload_file`: corrected to `upload(key, local_path, options)`.
- New regression tests in `media_service/tests/test_regressions.py`:
  - `test_key_first_then_local_path` — asserts the client receives `(key, local_path, options)` in that order.
  - `test_dict_values_are_json_serialized` — asserts `finish_job` binds a JSON *string* for dict `asset_values` (fake pool captures the bound params).
- Reset the three jobs again (`PENDING`, `attempts=0`, asset → `UPLOADED`).
- Full suite: **95 passed**.

---

## Problem 6 — `PermissionError [WinError 32]` on freshly-written derivatives (Windows lock race)

**Symptom (next run, after Problem 5's fixes):** probe reached `DONE`, but thumbnail/proxy failed with `PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: '…\media-thumbnail-…\thumb.jpg'` (and `proxy.mp4`). Leftover `media-*` temp dirs in `%TEMP%`; storage still only had `source.mp4`.

**Root cause:** Windows file-lock race. Right after ffmpeg writes the derivative into `%TEMP%`, **Windows Defender real-time scanning takes a handle** to the new file. The immediately-following open for upload hits a sharing violation, and the same lock makes `TemporaryDirectory` cleanup fail. Identical timing on every retry → consistent failures. Aggravated by storage3 opening the path itself (`open(file, "rb")` at `file_api.py:570`) without closing the handle.

**Fix:**
- `storage.py:upload_file` now reads the file into **bytes** with a short retry (`_read_with_retry`: 5 tries × 250 ms on `PermissionError`/`OSError`) and passes `bytes` to `.upload()` — accepted natively, sidesteps the lock and storage3's leaked handle.
- `worker.py`: `TemporaryDirectory(..., ignore_cleanup_errors=True)` (Python ≥3.10) so locked-file cleanup can never fail an already-successful job.
- Regression tests: bytes payload + retry-once-then-succeed + raises-after-exhausting.

---

## Problem 7 — cleanup job removed 0 objects (dict vs attribute)

**Symptom:** While resetting jobs, the asset turned out to be soft-deleted (user clicked Remove) with a `DONE` cleanup job — but `source.mp4` was still in storage.

**Root cause:** `handle_cleanup` read entry names via `getattr(e, "name", None)`. storage3's `list()` returns **dicts**, so every name came back `None`, `existing` was empty, and `remove([])` did nothing.

**Fix:** `worker.py:handle_cleanup` now reads `e["name"]` for dicts with an attribute fallback; leftover object removed and the soft-deleted row hard-deleted as one-time recovery.

---

## Problem 8 — `TypeError: Header value must be str or bytes, not <class 'bool'>` (storage3 quirk)

**Symptom (next run, after Problem 6/7 fixes):** probe `DONE`, but thumbnail/proxy jobs crashed with `TypeError: Header value must be str or bytes, not <class 'bool'>` from httpx, deep inside storage3's `_upload_or_update`.

**Root cause:** `storage.py` passed `"upsert": True` (Python **bool**) in the file options. storage3 copies option values **straight into HTTP headers** (`options["x-upsert"] = upsert` at `file_api.py:533-535`), and httpx rejects non-`str`/`bytes` header values. Every earlier bug (arg order, jsonb, Windows lock) had blocked the path before this line was reached — it only surfaced once uploads finally got that far. Tests missed it because the regression test fakes the bucket client and never exercises storage3's real option-to-header conversion.

**Fix:**
- `storage.py:upload_file`: `"upsert": "true"` (string) instead of `True`.
- Regression test tightened: asserts **all option values passed to upload are strings**.
- Reset thumbnail/proxy jobs for `af1fad98` (`WhatsApp Video…` — probe already DONE, metadata kept READY).
- Full suite: **97 passed**.

---

## Problem 9 — No way to preview a cloud video from the Library

**Symptom:** Processing completed (thumbnail + proxy `READY`), but the Library card offered only **Remove** — no play action existed for cloud items, and `New project` stays disabled for them by design (NewProject needs a local `File`).

**Fix (frontend only):**
- `Library.jsx`: play overlay on the thumbnail + **Preview** action for local items and cloud items with `proxy_status === "READY"`. Cloud preview fetches a fresh signed proxy URL from `GET /api/assets/{id}/preview-url` at click time (avoids expiry); local items play their object URL. Player modal (Escape / backdrop to close, "Preparing the preview…" while the URL loads, errors surface in the page banner).
- `styles.css`: `.lib-play` (hover/focus overlay), `.lib-player` (max-height 64vh), `.modal-wide` (900px).
- Honest tooltip on the disabled cloud **New project**: "Starting a project from a cloud video isn't supported yet."
- `vite build` clean. Backend untouched.

---

## State at hand-off (final)

- All fixes in place (Problems 1–8); regression suite green.
- Latest asset `af1fad98` (`WhatsApp Video 2026-10-10 at 23.12.49.mp4`): probe DONE, thumbnail/proxy reset to `PENDING`/`attempts=0` — will complete on next worker start.
- No services running (user starts them manually).

---

## Operational notes

- **Ports:** backend `:8010`, media `:8020`, Vite `:5173` (listens on `[::1]` only — use `localhost`, not `127.0.0.1`).
- **Run exactly one instance** of backend, media, and worker. Duplicates appeared several times this session (user-launched + background-launch); with `SKIP LOCKED` they're not corrupting, but they make logs misleading and one media instance fails to bind.
- **Vite proxy (verified working):** `/api/uploads` + `/api/assets` → `:8020`; everything else under `/api` → `:8010`. Earlier "proxy broken" readings were IPv4/IPv6 artifacts.
- **Storage contract (verified live):** create via `POST /object/upload/sign/{bucket}/{path}`; upload via **PUT** to the signed URL with multipart form; headers `apikey` + `Authorization: Bearer <user JWT>` + `x-upsert: false`. A `POST` upload hits create-sign and stores nothing (the deceptive-200 trap behind Problem 1).
- **Policies on live DB (all coexist):** user-added `Allow authenticated uploads/read/delete` (`to authenticated`) + our `media_objects_insert_own` / `media_objects_select_own`. Harmless duplicates.
- **ffmpeg:** `C:\ffmpeg\bin` (9.0.2); also pinned via `FFMPEG_BIN_DIR` in `.env` so any launcher works.
- **Tests:** `.venv\Scripts\python.exe -m pytest media_service\tests backend\tests -q` (refresh PATH first: `$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")`).
- **Worker logs:** `storage/logs/worker.err.log` (claims, `done in Ns`, failures, reaper warnings). API access logs: `media.out.log`. Startup traces: `*.err.log`.

---

## State at hand-off

- All backend/media/worker processes **stopped** (user will start them manually).
- Asset `ea56061c` (`Vision Quality.mp4`): source in storage, 3 jobs reset to `PENDING`/attempts=0 — will process on next worker start.
- Frontend progress banner + timeout in place; stale-row cleanup done; reaper + ffmpeg resolver in place.
- Next step: user starts backend `:8010`, media `:8020`, one worker, Vite — then hard-refreshes the Library tab and verifies `Waiting… → Processing… → READY`.
