// Library state shared across pages for this browser session. Uploaded videos keep their
// File so they can start a project; the sample items from library.js have no file.
// Replace with the Library API when it exists.
import { useSyncExternalStore } from "react";
import { LIBRARY } from "./library.js";

const MAX_BYTES = 500e6;
const MAX_SECONDS = 600;

let uploads = [];
let snapshot = [...LIBRARY];
const listeners = new Set();

function publish() {
  snapshot = [...uploads, ...LIBRARY];
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

/** Add video files. Returns { added: item[], errors: string[] }. */
export async function addVideos(files) {
  const added = [];
  const errors = [];
  for (const f of files) {
    if (!f.type.startsWith("video/") && !/\.(mkv|mov|mp4|webm)$/i.test(f.name)) {
      errors.push(`${f.name} isn't a video. Use MP4, MOV, WebM or MKV.`);
      continue;
    }
    if (f.size > MAX_BYTES) { errors.push(`${f.name} is over 500 MB.`); continue; }
    const url = URL.createObjectURL(f);
    const duration_s = await probe(url);
    if (duration_s && duration_s > MAX_SECONDS) { errors.push(`${f.name} is longer than 10 minutes.`); continue; }
    const item = { id: `up-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, name: f.name, size: f.size,
                   duration_s, uploaded_at: Date.now(), url, file: f, local: true };
    uploads = [item, ...uploads];
    added.push(item);
  }
  publish();
  return { added, errors };
}

export function removeVideo(id) {
  const item = uploads.find((u) => u.id === id);
  if (item) URL.revokeObjectURL(item.url);
  uploads = uploads.filter((u) => u.id !== id);
  publish();
}

export function useLibrary() {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => snapshot);
}

export const stripExt = (name) => name.replace(/\.[^.]+$/, "");
