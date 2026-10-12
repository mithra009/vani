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
  const body = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
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
export function subscribe(projectId, { onSnapshot, onError, onHeartbeat }) {
  const url = withToken(`/api/editor/projects/${projectId}/events`);
  const es = new EventSource(url);

  es.addEventListener("snapshot", (e) => {
    try { onSnapshot?.(JSON.parse(e.data)); } catch { /* ignore */ }
  });
  es.addEventListener("error", (e) => {
    if (e.data) {
      try { onError?.(JSON.parse(e.data)); } catch { /* ignore */ }
    }
  });
  es.addEventListener("heartbeat", () => onHeartbeat?.());

  es.onerror = () => {
    // EventSource reconnects automatically; we just log it.
  };

  return () => es.close();
}
