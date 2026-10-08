// API client for the backend contract in PLAN.md §6. Falls back to the in-browser demo
// (mock.js) when the backend isn't reachable, so the UI is usable before FastAPI exists.
import { mock } from "./mock.js";

async function http(path, opts = {}) {
  const res = await fetch(`/api${path}`, opts);
  const body = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) throw new Error(body?.detail || body?.error || `Request failed (${res.status}).`);
  return body;
}

const real = {
  health: () => http("/health"),
  listJobs: () => http("/jobs"),
  async createJob(file, srcLang, tgtLang, onUpload, mode = "dub") {
    // XHR rather than fetch so we can report upload progress.
    return new Promise((resolve, reject) => {
      const form = new FormData();
      form.append("video", file);
      form.append("src_lang", srcLang);
      form.append("tgt_lang", tgtLang);
      form.append("mode", mode);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/jobs");
      xhr.upload.onprogress = (e) => e.lengthComputable && onUpload?.(e.loaded / e.total);
      xhr.onload = () => {
        let body = null;
        try { body = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
        xhr.status < 300 ? resolve(body) : reject(new Error(body?.detail || `Upload failed (${xhr.status}).`));
      };
      xhr.onerror = () => reject(new Error("Upload failed. Check your connection and try again."));
      xhr.send(form);
    });
  },
  getJob: (id) => http(`/jobs/${id}`),
  uploadNarration(id, take) {
    const form = new FormData();
    form.append("audio", take.blob, take.name || "narration");
    form.append("offset_s", String(take.offset_s));
    return http(`/jobs/${id}/narration`, { method: "POST", body: form });
  },
  updateSegments: (id, segments) =>
    http(`/jobs/${id}/segments`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ segments }),
    }),
  startDub(id, settings) {
    const sample = settings.voice?.sample;
    if (sample instanceof Blob) {
      // A voice-clone sample (uploaded or recorded) goes as multipart next to the JSON settings.
      const { sample: _, ...voice } = settings.voice;
      const form = new FormData();
      form.append("settings", JSON.stringify({ ...settings, voice }));
      form.append("voice_sample", sample, "voice-sample");
      return http(`/jobs/${id}/dub`, { method: "POST", body: form });
    }
    return http(`/jobs/${id}/dub`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings),
    });
  },
  regenerate: (id, idx) => http(`/jobs/${id}/segments/${idx}/regenerate`, { method: "POST" }),
  subscribe(id, cb) {
    const es = new EventSource(`/api/jobs/${id}/events`);
    es.onmessage = (e) => { try { cb(JSON.parse(e.data)); } catch { /* ignore */ } };
    return () => es.close();
  },
  downloads: (job) => ({
    video: `/api/jobs/${job.id}/output.mp4`,
    srtSource: `/api/jobs/${job.id}/subs.source.srt`,
    srtTarget: `/api/jobs/${job.id}/subs.target.srt`,
  }),
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
