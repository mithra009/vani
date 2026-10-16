// Editor service client: projects, chunks, voice, SSE, narration upload.
// Mirrors the contract in editor_service/routes.py.
import { accessToken, withToken } from "./supabase.js";

let onUnauthorized = () => {};
export const setEditorUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

function detail(body, status) {
  if (body?.message) return body.message;
  if (body?.detail) return typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
  return `Request failed (${status}).`;
}

async function http(path, opts = {}) {
  const t = accessToken();
  const headers = {
    ...(opts.headers || {}),
    ...(t ? { Authorization: `Bearer ${t}` } : {}),
  };
  const res = await fetch(`/api/editor${path}`, { ...opts, headers });
  if (res.status === 204) return null;
  const text = await res.text();
  let body = null;
  if (text && res.headers.get("content-type")?.includes("json")) {
    try { body = JSON.parse(text); }
    catch { if (res.ok) throw new Error(`The server sent an unreadable response (${res.status}).`); }
  }
  if (res.status === 401) onUnauthorized();
  if (!res.ok) throw Object.assign(new Error(detail(body, res.status)), { code: body?.code, status: res.status });
  return body;
}

const json = (body) => ({ headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

// ------------------------------------------------------------------ projects

export const listProjects = () => http("/projects");

export const createProject = (body) => http("/projects", { method: "POST", ...json(body) });

export const getProject = (id) => http(`/projects/${id}`);

export const deleteProject = (id) => http(`/projects/${id}`, { method: "DELETE" });

export const retryProject = (id) => http(`/projects/${id}/retry`, { method: "POST" });

export const setVoice = (id, voice, settingsVersion) =>
  http(`/projects/${id}/voice`, { method: "PUT", ...json({ voice, settings_version: settingsVersion }) });

export const estimateProject = (id) => http(`/projects/${id}/estimate`, { method: "POST" });

// ------------------------------------------------------------------ narration

export const narrationInit = (projectId, ext) =>
  http(`/projects/${projectId}/narration/init`, { method: "POST", ...json({ ext }) });

export const narrationComplete = (projectId, ext) =>
  http(`/projects/${projectId}/narration/complete`, { method: "POST", ...json({ ext }) });

// ------------------------------------------------------------------ chunks

export const editChunk = (projectId, chunkId, revision, changes) =>
  http(`/projects/${projectId}/chunks/${chunkId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", "If-Match": String(revision) },
    body: JSON.stringify(changes),
  });

export const regenerateChunk = (projectId, chunkId) =>
  http(`/projects/${projectId}/chunks/${chunkId}/regenerate`, { method: "POST" });

export const chunkAudioUrl = (projectId, chunkId) =>
  http(`/projects/${projectId}/chunks/${chunkId}/audio-url`);

// ------------------------------------------------------------------ SSE

/**
 * Subscribe to project events. Returns a cleanup function.
 * @param {string} projectId
 * @param {{ onSnapshot, onError, onHeartbeat }} handlers
 */
export function subscribe(projectId, { onSnapshot, onError, onHeartbeat, onConnection }) {
  const url = withToken(`/api/editor/projects/${projectId}/events`);
  const es = new EventSource(url);
  const parse = (e, kind) => {
    try { return JSON.parse(e.data); }
    catch (err) {
      console.error(`Bad ${kind} event`, err, e.data);
      onError?.({ code: "bad_event", message: `Live update couldn't be read (${kind}).` });
      return null;
    }
  };

  es.addEventListener("snapshot", (e) => { const d = parse(e, "snapshot"); if (d) { onConnection?.(true); onSnapshot?.(d); } });
  es.addEventListener("error", (e) => {
    if (e.data) { const d = parse(e, "error"); if (d) onError?.(d); }
  });
  es.addEventListener("heartbeat", () => { onConnection?.(true); onHeartbeat?.(); });
  // Transport drop: EventSource retries by itself, but the user must see that updates paused.
  es.onerror = () => onConnection?.(false);

  return () => es.close();
}

// ------------------------------------------------------------------ split / merge (phase 2)

export const splitChunk = (projectId, chunkId, revision, atChar) =>
  http(`/projects/${projectId}/chunks/${chunkId}/split`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "If-Match": String(revision) },
    body: JSON.stringify({ at_char: atChar }),
  });

export const mergeChunks = (projectId, first, second) =>
  http(`/projects/${projectId}/chunks/merge`, {
    method: "POST",
    ...json({ first_id: first.id, first_revision: first.revision, second_id: second.id, second_revision: second.revision }),
  });

// ------------------------------------------------------------------ timeline (phase 2)

export const getTimeline = (projectId) => http(`/projects/${projectId}/timeline`);

/** Resolves {version, doc}. On 409 the error carries `.current` = {version, doc} for rebasing. */
export async function saveOps(projectId, baseVersion, ops) {
  const t = accessToken();
  const res = await fetch(`/api/editor/projects/${projectId}/timeline/ops`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(t ? { Authorization: `Bearer ${t}` } : {}) },
    body: JSON.stringify({ base_version: baseVersion, ops }),
  });
  const body = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (res.status === 401) onUnauthorized();
  if (!res.ok) {
    throw Object.assign(new Error(detail(body, res.status)), {
      code: body?.code, status: res.status,
      current: res.status === 409 && body?.doc ? { version: body.version, doc: body.doc } : null,
    });
  }
  return body;
}

export const mediaInit = (projectId, filename, durationS) =>
  http(`/projects/${projectId}/media/init`, { method: "POST", ...json({ filename, duration_s: durationS }) });

export const mediaComplete = (projectId, mediaId) =>
  http(`/projects/${projectId}/media/${mediaId}/complete`, { method: "POST" });

export const mediaUrl = (projectId, mediaId) => http(`/projects/${projectId}/media/${mediaId}/url`);

// ------------------------------------------------------------------ exports (phase 3)

export const createExport = (projectId, body) => http(`/projects/${projectId}/exports`, { method: "POST", ...json(body) });

export const listExports = (projectId) => http(`/projects/${projectId}/exports`);

export const exportUrl = (projectId, exportId) => http(`/projects/${projectId}/exports/${exportId}/url`);
