// API client for the backend contract in PLAN.md §6. Falls back to the in-browser demo
// (mock.js) when the backend isn't reachable, so the UI is usable before FastAPI exists.
import { mock } from "./mock.js";
import { accessToken, withToken } from "./supabase.js";

let onUnauthorized = () => {};
/** Called when the backend says the session is missing or expired. */
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

function detail(body, status) {
  const d = body?.detail;
  if (Array.isArray(d)) return d.map((x) => x.msg?.replace(/^Value error, /, "")).join(" ");
  return d || body?.error || `Request failed (${status}).`;
}

async function http(path, opts = {}) {
  const t = accessToken();
  const headers = { ...(opts.headers || {}), ...(t ? { Authorization: `Bearer ${t}` } : {}) };
  const res = await fetch(`/api${path}`, { ...opts, headers });
  const body = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (res.status === 401 && !path.startsWith("/auth/")) onUnauthorized();
  if (!res.ok) throw new Error(detail(body, res.status));
  return body;
}

/** Media URLs in a job can't carry an Authorization header, so they get the token. */
function authed(job) {
  if (!job || typeof job !== "object") return job;
  return {
    ...job,
    video_url: withToken(job.video_url),
    output_url: withToken(job.output_url),
    narration: job.narration ? { ...job.narration, url: withToken(job.narration.url) } : job.narration,
  };
}

export const authApi = {
  signUp: (form) => http("/auth/signup", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form),
  }),
  signIn: (identifier, password) => http("/auth/signin", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ identifier, password }),
  }),
  usernameAvailable: (u) => http(`/auth/username-available?username=${encodeURIComponent(u)}`),
  me: () => http("/me"),
};

const real = {
  health: () => http("/health"),
  listJobs: () => http("/jobs"),
  async createJob(file, srcLang, tgtLang, onUpload, mode = "dub", name = "") {
    // XHR rather than fetch so we can report upload progress.
    return new Promise((resolve, reject) => {
      const form = new FormData();
      form.append("video", file);
      form.append("src_lang", srcLang);
      form.append("tgt_lang", tgtLang);
      form.append("mode", mode);
      if (name) form.append("name", name);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/jobs");
      const t = accessToken();
      if (t) xhr.setRequestHeader("Authorization", `Bearer ${t}`);
      xhr.upload.onprogress = (e) => e.lengthComputable && onUpload?.(e.loaded / e.total);
      xhr.onload = () => {
        let body = null;
        try { body = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
        if (xhr.status === 401) onUnauthorized();
        xhr.status < 300 ? resolve(authed(body)) : reject(new Error(detail(body, xhr.status)));
      };
      xhr.onerror = () => reject(new Error("Upload failed. Check your connection and try again."));
      xhr.send(form);
    });
  },
  getJob: (id) => http(`/jobs/${id}`).then(authed),
  // Needs PATCH/DELETE /api/jobs/{id} on the backend (projects backend, not built yet).
  renameJob: (id, name) => http(`/jobs/${id}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }),
  }),
  deleteJob: (id) => http(`/jobs/${id}`, { method: "DELETE" }),
  uploadNarration(id, take) {
    const form = new FormData();
    form.append("audio", take.blob, take.name || "narration");
    form.append("offset_s", String(take.offset_s));
    return http(`/jobs/${id}/narration`, { method: "POST", body: form }).then(authed);
  },
  updateSegments: (id, segments) =>
    http(`/jobs/${id}/segments`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ segments }),
    }).then(authed),
  startDub(id, settings) {
    const sample = settings.voice?.sample;
    if (sample instanceof Blob) {
      // A voice-clone sample (uploaded or recorded) goes as multipart next to the JSON settings.
      const { sample: _, ...voice } = settings.voice;
      const form = new FormData();
      form.append("settings", JSON.stringify({ ...settings, voice }));
      form.append("voice_sample", sample, "voice-sample");
      return http(`/jobs/${id}/dub`, { method: "POST", body: form }).then(authed);
    }
    return http(`/jobs/${id}/dub`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings),
    }).then(authed);
  },
  regenerate: (id, idx) => http(`/jobs/${id}/segments/${idx}/regenerate`, { method: "POST" }).then(authed),
  subscribe(id, cb) {
    const es = new EventSource(withToken(`/api/jobs/${id}/events`));
    es.onmessage = (e) => { try { cb(authed(JSON.parse(e.data))); } catch { /* ignore */ } };
    return () => es.close();
  },
  downloads: (job) => ({
    video: withToken(`/api/jobs/${job.id}/output.mp4`),
    srtSource: withToken(`/api/jobs/${job.id}/subs.source.srt`),
    srtTarget: withToken(`/api/jobs/${job.id}/subs.target.srt`),
  }),
  previewUrl: (voiceId, lang) => withToken(`/api/voices/${voiceId}/preview?lang=${lang}`),
};

let impl = null;
let mode = null;

export async function initApi() {
  if (impl) return mode;
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 1500);
    const res = await fetch("/api/health", { signal: ctl.signal });
    clearTimeout(t);
    if (!res.ok || !res.headers.get("content-type")?.includes("json")) throw new Error();
    impl = real;
    mode = "live";
  } catch {
    impl = mock;
    mode = "demo";
  }
  return mode;
}

export const api = new Proxy({}, {
  get: (_, key) => (...args) => {
    if (!impl) throw new Error("initApi() must finish before using the API.");
    return impl[key](...args);
  },
});
