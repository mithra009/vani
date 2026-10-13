// Timeline model — a line-for-line port of editor_service/timeline.py so edits apply instantly
// in the browser (G8) and the server re-validates the same ops. Keep the two in sync.
//
// Two clocks: source time (chunk anchors) and timeline time (the edited output). Video clips
// are contiguous; deleting one ripples later clips left and hides voice anchored in it (D2).

export const MIN_CLIP_S = 0.1;
export const GAIN_MIN_DB = -60;
export const GAIN_MAX_DB = 12;
const EPS = 1e-6;

export class OpError extends Error {}

export const newId = (prefix) => `${prefix}${Math.random().toString(16).slice(2, 12)}`;
const clone = (x) => (typeof structuredClone === "function" ? structuredClone(x) : JSON.parse(JSON.stringify(x)));

export function defaultDoc(durationS) {
  return {
    video: [{ id: "vc0", src_in: 0, src_out: Math.round(durationS * 1000) / 1000 }],
    original_audio: { gain_db: -12, muted: false, auto_duck: true },
    voice: { gain_db: 0, clips: {} },
    music: { gain_db: -18, clips: [] },
    captions: { enabled: false },
  };
}

// ------------------------------------------------------------------ mapping

export function videoLayout(doc) {
  let t = 0;
  return doc.video.map((c) => {
    const out = { ...c, t };
    t += c.src_out - c.src_in;
    return out;
  });
}

export const durationT = (doc) => doc.video.reduce((a, c) => a + (c.src_out - c.src_in), 0);

export function srcToT(doc, s) {
  for (const c of videoLayout(doc)) if (c.src_in - EPS <= s && s < c.src_out) return c.t + (s - c.src_in);
  return null;
}

export function voiceClip(doc, chunkId) {
  return { offset: 0, trim_in: 0, trim_out: 0, gain_db: 0, muted: false, detached_t: null, ...(doc.voice.clips[chunkId] || {}) };
}

/** → { placed: [{chunk_id, t, length, trim_in, gain_db, muted, flags}], hidden: [{chunk_id, reason}] } */
export function layout(doc, chunks) {
  const placed = [], hidden = [];
  const end = durationT(doc);
  const vl = videoLayout(doc);
  for (const ch of [...chunks].sort((a, b) => a.idx - b.idx)) {
    const cid = String(ch.id);
    const vc = voiceClip(doc, cid);
    if (ch.anchor_src_s == null) { hidden.push({ chunk_id: cid, reason: "unplaced" }); continue; }
    if (!ch.audio_duration_s) { hidden.push({ chunk_id: cid, reason: "no_audio" }); continue; }
    const anchor = Number(ch.anchor_src_s);
    let t;
    if (vc.detached_t != null) t = Number(vc.detached_t);
    else {
      const m = srcToT(doc, anchor);
      if (m == null) { hidden.push({ chunk_id: cid, reason: "video_cut" }); continue; }
      t = m + vc.offset;
    }
    const length = Math.max(0, Number(ch.audio_duration_s) - vc.trim_in - vc.trim_out);
    const p = { chunk_id: cid, t, length, trim_in: vc.trim_in, gain_db: vc.gain_db, muted: vc.muted, flags: [] };
    if (t < -EPS) p.flags.push("before_start");
    if (t + length > end + EPS) p.flags.push("past_end");
    if (vc.detached_t == null && ch.anchor_len_s != null) {
      const spanEnd = anchor + Number(ch.anchor_len_s);
      const home = vl.find((c) => c.src_in - EPS <= anchor && anchor < c.src_out - EPS);
      if (home && spanEnd > home.src_out + 0.05) p.flags.push("on_cut");
    }
    placed.push(p);
  }
  const audible = placed.filter((p) => !p.muted).sort((a, b) => a.t - b.t);
  audible.forEach((a, i) => {
    for (const b of audible.slice(i + 1)) {
      if (b.t >= a.t + a.length - EPS) break;
      for (const x of [a, b]) if (!x.flags.includes("overlap")) x.flags.push("overlap");
    }
  });
  return { placed, hidden };
}

// ------------------------------------------------------------------ ops

function num(op, key, lo, hi) {
  const v = op[key];
  if (typeof v !== "number" || !Number.isFinite(v)) throw new OpError(`${op.type}: '${key}' must be a number.`);
  if ((lo != null && v < lo - EPS) || (hi != null && v > hi + EPS)) throw new OpError(`${op.type}: '${key}' must be between ${lo} and ${hi}, got ${v}.`);
  return v;
}

function videoIndex(doc, id) {
  const i = doc.video.findIndex((c) => c.id === id);
  if (i < 0) throw new OpError(`No video clip ${JSON.stringify(id)}.`);
  return i;
}

function checkVideo(doc) {
  if (!doc.video.length) throw new OpError("The video track can't be empty.");
  const spans = doc.video.map((c) => [c.src_in, c.src_out]).sort((a, b) => a[0] - b[0]);
  for (let i = 1; i < spans.length; i++) if (spans[i][0] < spans[i - 1][1] - EPS) throw new OpError("Video clips can't reuse the same part of the source.");
  for (const c of doc.video) if (c.src_out - c.src_in < MIN_CLIP_S - EPS) throw new OpError(`Video clips must be at least ${MIN_CLIP_S}s long.`);
}

const VOICE_FIELDS = { offset: [-30, 30], trim_in: [0, 600], trim_out: [0, 600], gain_db: [GAIN_MIN_DB, GAIN_MAX_DB] };
const TRACK_FIELDS = {
  original_audio: { gain_db: "gain", muted: "bool", auto_duck: "bool" },
  voice: { gain_db: "gain" },
  music: { gain_db: "gain" },
  captions: { enabled: "bool" },
};
const MUSIC_FIELDS = { t: [0, 3600], media_in: [0, 3600], media_out: [0, 3600], fade_in: [0, 30], fade_out: [0, 30], gain_db: [GAIN_MIN_DB, GAIN_MAX_DB] };

/** Apply one op to a copy. Returns [doc', inverse]. Throws OpError — never a silent no-op. */
export function apply(doc, op, { sourceS, chunkIds = null, media = null }) {
  if (!op || typeof op.type !== "string") throw new OpError(`Malformed op ${JSON.stringify(op)}`.slice(0, 200));
  const d = clone(doc);
  const k = op.type;
  let inv;

  if (k === "video.trim") {
    const i = videoIndex(d, op.clip_id);
    const old = { ...d.video[i] };
    d.video[i].src_in = num(op, "src_in", 0, sourceS);
    d.video[i].src_out = num(op, "src_out", 0, sourceS);
    if (d.video[i].src_out <= d.video[i].src_in) throw new OpError("video.trim: src_out must be after src_in.");
    checkVideo(d);
    inv = { type: "video.trim", clip_id: old.id, src_in: old.src_in, src_out: old.src_out };
  } else if (k === "video.split") {
    const i = videoIndex(d, op.clip_id);
    const c = d.video[i];
    const at = num(op, "at_src", c.src_in, c.src_out);
    const nw = { id: op.new_id || newId("vc"), src_in: at, src_out: c.src_out };
    c.src_out = at;
    d.video.splice(i + 1, 0, nw);
    checkVideo(d);
    inv = { type: "video.join", clip_id: c.id, next_id: nw.id };
  } else if (k === "video.join") {
    const i = videoIndex(d, op.clip_id), j = videoIndex(d, op.next_id);
    if (j !== i + 1 || Math.abs(d.video[i].src_out - d.video[j].src_in) > EPS) throw new OpError("video.join: clips must be next to each other in both orders.");
    const at = d.video[i].src_out;
    d.video[i].src_out = d.video[j].src_out;
    const [removed] = d.video.splice(j, 1);
    inv = { type: "video.split", clip_id: d.video[i].id, at_src: at, new_id: removed.id };
  } else if (k === "video.delete") {
    const i = videoIndex(d, op.clip_id);
    const [removed] = d.video.splice(i, 1);
    checkVideo(d);
    inv = { type: "video.insert", index: i, clip: removed };
  } else if (k === "video.insert") {
    const clip = op.clip;
    if (!clip || !clip.id) throw new OpError("video.insert: needs a clip with an id.");
    const idx = Math.trunc(num(op, "index", 0, d.video.length));
    const c = { id: clip.id, src_in: num({ ...clip, type: k }, "src_in", 0, sourceS), src_out: num({ ...clip, type: k }, "src_out", 0, sourceS) };
    if (d.video.some((x) => x.id === c.id)) throw new OpError(`video.insert: clip ${c.id} already exists.`);
    d.video.splice(idx, 0, c);
    checkVideo(d);
    inv = { type: "video.delete", clip_id: c.id };
  } else if (k === "video.move") {
    const i = videoIndex(d, op.clip_id);
    const to = Math.trunc(num(op, "index", 0, d.video.length - 1));
    d.video.splice(to, 0, d.video.splice(i, 1)[0]);
    inv = { type: "video.move", clip_id: op.clip_id, index: i };
  } else if (k === "voice.set") {
    const cid = op.chunk_id;
    if (typeof cid !== "string" || (chunkIds && !chunkIds.has(cid))) throw new OpError(`voice.set: no chunk ${cid}.`);
    const f = op.fields;
    if (!f || typeof f !== "object" || !Object.keys(f).length) throw new OpError("voice.set: 'fields' must be a non-empty object.");
    const old = voiceClip(d, cid);
    const clip = (d.voice.clips[cid] ||= {});
    for (const [key, v] of Object.entries(f)) {
      if (key in VOICE_FIELDS) clip[key] = num({ type: k, [key]: v }, key, ...VOICE_FIELDS[key]);
      else if (key === "muted") { if (typeof v !== "boolean") throw new OpError("voice.set: 'muted' must be true/false."); clip[key] = v; }
      else if (key === "detached_t") clip[key] = v == null ? null : num({ type: k, [key]: v }, key, 0, 3600);
      else throw new OpError(`voice.set: unknown field ${key}.`);
    }
    inv = { type: "voice.set", chunk_id: cid, fields: Object.fromEntries(Object.keys(f).map((x) => [x, old[x]])) };
  } else if (k === "track.set") {
    const allowed = TRACK_FIELDS[op.track];
    const f = op.fields;
    if (!allowed) throw new OpError(`track.set: unknown track ${op.track}.`);
    if (!f || !Object.keys(f).length) throw new OpError("track.set: 'fields' must be a non-empty object.");
    const old = {};
    for (const [key, v] of Object.entries(f)) {
      const t = allowed[key];
      if (!t) throw new OpError(`track.set: ${op.track} has no field ${key}.`);
      old[key] = d[op.track][key];
      if (t === "bool") { if (typeof v !== "boolean") throw new OpError(`track.set: '${key}' must be true/false.`); d[op.track][key] = v; }
      else d[op.track][key] = num({ type: k, [key]: v }, key, GAIN_MIN_DB, GAIN_MAX_DB);
    }
    inv = { type: "track.set", track: op.track, fields: old };
  } else if (k === "music.add") {
    const clip = op.clip;
    if (!clip || !clip.media_id) throw new OpError("music.add: needs a clip with a media_id.");
    if (media && !(clip.media_id in media)) throw new OpError(`music.add: no uploaded audio ${clip.media_id}.`);
    const mlen = media ? media[clip.media_id] : null;
    const defaults = { t: 0, media_in: 0, media_out: mlen, fade_in: 0, fade_out: 0, gain_db: 0 };
    const c = { id: clip.id || newId("mc"), media_id: clip.media_id };
    for (const [key, [lo, hi0]] of Object.entries(MUSIC_FIELDS)) {
      const hi = (key === "media_in" || key === "media_out") && mlen ? mlen : hi0;
      c[key] = num({ type: k, [key]: key in clip ? clip[key] : defaults[key] }, key, lo, hi);
    }
    if (c.media_out <= c.media_in) throw new OpError("music.add: media_out must be after media_in.");
    if (d.music.clips.some((x) => x.id === c.id)) throw new OpError(`music.add: clip ${c.id} already exists.`);
    d.music.clips.push(c);
    inv = { type: "music.delete", clip_id: c.id };
  } else if (k === "music.delete") {
    const i = d.music.clips.findIndex((c) => c.id === op.clip_id);
    if (i < 0) throw new OpError(`music.delete: no clip ${op.clip_id}.`);
    const [removed] = d.music.clips.splice(i, 1);
    inv = { type: "music.add", clip: removed };
  } else if (k === "music.set") {
    const c = d.music.clips.find((x) => x.id === op.clip_id);
    const f = op.fields;
    if (!c) throw new OpError(`music.set: no clip ${op.clip_id}.`);
    if (!f || !Object.keys(f).length) throw new OpError("music.set: 'fields' must be a non-empty object.");
    const old = {};
    for (const [key, v] of Object.entries(f)) {
      if (!(key in MUSIC_FIELDS)) throw new OpError(`music.set: unknown field ${key}.`);
      old[key] = c[key];
      c[key] = num({ type: k, [key]: v }, key, ...MUSIC_FIELDS[key]);
    }
    if (c.media_out <= c.media_in) throw new OpError("music.set: media_out must be after media_in.");
    inv = { type: "music.set", clip_id: c.id, fields: old };
  } else {
    throw new OpError(`Unknown op type ${k}.`);
  }
  return [d, inv];
}

export function applyAll(doc, ops, ctx) {
  const invs = [];
  ops.forEach((op, n) => {
    let inv;
    try { [doc, inv] = apply(doc, op, ctx); }
    catch (e) { throw new OpError(`Op ${n} (${op?.type ?? "?"}): ${e.message}`); }
    invs.push(inv);
  });
  return [doc, invs];
}
