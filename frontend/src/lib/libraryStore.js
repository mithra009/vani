// Library state: videos live in the media service (Supabase Storage) and survive refresh.
// Uploads go straight from the browser to Supabase via a signed URL; the API only hands
// out URLs and metadata. When the media backend isn't reachable (demo mode), files fall
// back to session-only items like before.
import { useSyncExternalStore } from "react";
import { api } from "./api.js";
import { accessToken } from "./supabase.js";
import { LIBRARY } from "./library.js";

const MAX_BYTES = 500e6;
const MAX_SECONDS = 600;
const POLL_MS = 2500;
const POLL_MAX_TRIES = 480; // ~20 min of processing updates

let serverAssets = [];   // cloud-backed items from the media API
let sessionItems = [];   // session-only fallbacks (File kept in memory)
let snapshot = [...sessionItems, ...LIBRARY];
const listeners = new Set();

function publish() {
  snapshot = [...serverAssets, ...sessionItems, ...LIBRARY];
  listeners.forEach((l) => l());
}

function probe(url) {
  return new Promise((res) => {
    const v = document.createElement("video");
    v.preload = "metadata";
    v.onloadedmetadata = () => res(v.duration || null);
    v.onerror = () => res(null);
    v.src = url;
  });
}

/** Map a media-API asset row to the shape Library.jsx / NewProject.jsx read. */
export function fromAsset(a) {
  return {
    id: a.id,
    name: a.original_filename,
    size: a.size_bytes,
    duration_s: a.duration_ms ? a.duration_ms / 1000 : null,
    uploaded_at: a.created_at ? Date.parse(a.created_at) : Date.now(),
    lang: null,
    cover: a.thumbnail_url ? `url("${a.thumbnail_url}") center/cover no-repeat` : null,
    url: null,
    file: null,
    local: false,
    remote: true,
    status: a.status,
    metadata_status: a.metadata_status,
    thumbnail_status: a.thumbnail_status,
    proxy_status: a.proxy_status,
  };
}

/** Re-fetch the owner's assets (call on Library mount so the list survives refresh). */
export async function refreshLibrary() {
  try {
    const list = await api.listAssets();
    serverAssets = (list || []).map(fromAsset);
    publish();
    // Resume status polling for anything still processing before the reload.
    for (const a of serverAssets) {
      if (a.status !== "READY" && a.status !== "FAILED") pollAsset(a.id);
    }
    return true;
  } catch {
    return false;
  }
}

/** PUT the file to the signed Supabase upload URL (XHR for progress).
 * Mirrors @supabase/storage-js uploadToSignedUrl exactly: PUT, multipart body with a
 * "file" part, the publishable key as apikey, the user's JWT as Authorization, and the
 * upload token only in the URL query string. A POST here would hit the *create-sign*
 * endpoint instead and silently store nothing. */
function uploadToStorage(file, uploadUrl, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", uploadUrl);
    const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || "";
    if (key) xhr.setRequestHeader("apikey", key);
    // The user's JWT (not the anon key) as Authorization: the storage INSERT policy
    // checks auth.uid() against the {user_id}/{asset_id}/ folder.
    const userToken = accessToken();
    if (userToken) xhr.setRequestHeader("Authorization", `Bearer ${userToken}`);
    else if (key) xhr.setRequestHeader("Authorization", `Bearer ${key}`);
    xhr.setRequestHeader("x-upsert", "false");
    const form = new FormData();
    form.append("cacheControl", "3600");
    form.append("file", file, file.name);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    xhr.onload = () => {
      if (xhr.status < 300) resolve();
      else {
        let msg = null;
        try {
          const b = JSON.parse(xhr.responseText);
          msg = b?.message || b?.error || null;
        } catch { /* not JSON */ }
        reject(new Error(msg || `Storage upload failed (${xhr.status}).`));
      }
    };
    xhr.onerror = () => reject(new Error("Storage upload failed. Check your connection and try again."));
    xhr.timeout = 600000; // never hang silently — fail with a clear message instead
    xhr.ontimeout = () => reject(new Error("Storage upload timed out. Check your connection and try again."));
    xhr.send(form);
  });
}

/** Watch an asset's statuses until READY/FAILED; refresh cover as thumbnails land. */
async function pollAsset(assetId) {
  for (let i = 0; i < POLL_MAX_TRIES; i++) {
    await new Promise((r) => setTimeout(r, POLL_MS));
    const item = serverAssets.find((s) => s.id === assetId);
    if (!item) return; // removed while processing
    let a;
    try { a = await api.getAsset(assetId); } catch { continue; }
    Object.assign(item, fromAsset(a));
    publish();
    if (a.status === "READY" || a.status === "FAILED") return;
  }
}

function sessionItem(f, duration_s) {
  const url = URL.createObjectURL(f);
  return { id: `up-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, name: f.name, size: f.size,
           duration_s, uploaded_at: Date.now(), url, file: f, local: true };
}

/** Add video files. Returns { added: item[], errors: string[] }.
 * onProgress(fileName, phase, fraction) reports the pipeline position:
 * "init" → requesting a signed URL, "upload" → PUT to storage (fraction 0..1),
 * "finalize" → telling the backend to verify and enqueue. */
export async function addVideos(files, onProgress) {
  const added = [];
  const errors = [];
  for (const f of files) {
    if (!f.type.startsWith("video/") && !/\.(mkv|mov|mp4|webm)$/i.test(f.name)) {
      errors.push(`${f.name} isn't a video. Use MP4, MOV, WebM or MKV.`);
      continue;
    }
    if (f.size > MAX_BYTES) { errors.push(`${f.name} is over 500 MB.`); continue; }
    const probeUrl = URL.createObjectURL(f);
    const duration_s = await probe(probeUrl);
    if (duration_s && duration_s > MAX_SECONDS) {
      URL.revokeObjectURL(probeUrl);
      errors.push(`${f.name} is longer than 10 minutes.`);
      continue;
    }

    let init = null;
    try {
      onProgress?.(f.name, "init");
      init = await api.initUpload({
        original_filename: f.name,
        size_bytes: f.size,
        duration_ms: duration_s ? Math.round(duration_s * 1000) : null,
      });
    } catch {
      init = null; // media backend down or demo mode → session-only fallback
    }

    if (!init) {
      // Keep the old behaviour so the UI still works without the backend.
      URL.revokeObjectURL(probeUrl);
      const item = sessionItem(f, duration_s);
      sessionItems = [item, ...sessionItems];
      added.push(item);
      publish();
      continue;
    }

    URL.revokeObjectURL(probeUrl);
    try {
      onProgress?.(f.name, "upload", 0);
      await uploadToStorage(f, init.uploadUrl, (frac) => onProgress?.(f.name, "upload", frac));
      onProgress?.(f.name, "finalize");
      const a = await api.completeUpload(init.assetId);
      const item = fromAsset(a);
      if (!item.duration_s && duration_s) item.duration_s = duration_s;
      serverAssets = [item, ...serverAssets];
      added.push(item);
      publish();
      pollAsset(item.id);
    } catch (e) {
      errors.push(`${f.name}: ${e.message}`);
    }
  }
  return { added, errors };
}

/** Remove a video: soft-delete on the server (bytes go shortly after), or drop a session item. */
export async function removeVideo(id) {
  const remote = serverAssets.find((u) => u.id === id);
  if (remote) {
    serverAssets = serverAssets.filter((u) => u.id !== id);
    publish();
    try { await api.deleteAsset(id); } catch { /* already gone or backend down */ }
    return;
  }
  const item = sessionItems.find((u) => u.id === id);
  if (item) URL.revokeObjectURL(item.url);
  sessionItems = sessionItems.filter((u) => u.id !== id);
  publish();
}

export function useLibrary() {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => snapshot);
}

export const stripExt = (name) => name.replace(/\.[^.]+$/, "");
