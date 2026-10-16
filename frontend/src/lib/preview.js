// Live preview (design §10.4): AudioContext is the master clock; the proxy <video> is slaved to
// it and seeks across cuts. Voice chunks and music are decoded once into AudioBuffers and
// scheduled at their timeline positions. Cut boundaries may stutter a frame; export is exact.
import { durationT, layout, videoLayout } from "./timeline.js";

const DRIFT_S = 0.08;
const TICK_MS = 50;
const dbToGain = (db) => Math.pow(10, db / 20);

export class PreviewEngine {
  /** loaders: { chunkUrl(chunk) → Promise<url>, mediaUrl(mediaId) → Promise<url> } */
  constructor(video, loaders, onTime, onError, onState) {
    this.onState = onState;          // (playing) => void: the single source of truth for the button
    this.video = video;
    this.loaders = loaders;
    this.onTime = onTime;
    this.onError = onError;
    this.ctx = null;
    this.buffers = new Map();      // cache key → Promise<AudioBuffer>
    this.sources = [];
    this.playing = false;
    this.t = 0;
  }

  _ensureCtx() {
    if (this.ctx) return;
    this.ctx = new AudioContext();
    this.master = this.ctx.createGain();
    this.master.connect(this.ctx.destination);
    this.origGain = this.ctx.createGain();
    this.origGain.connect(this.master);
    try {
      this.ctx.createMediaElementSource(this.video).connect(this.origGain);
    } catch (e) {
      // Already connected (hot reload) or a cross-origin proxy without CORS: say so, keep going.
      this.onError?.(`Original audio can't be mixed in preview: ${e.message}`);
    }
  }

  _buffer(key, urlPromise) {
    if (!this.buffers.has(key)) {
      const p = urlPromise()
        .then((url) => fetch(url))
        .then((r) => { if (!r.ok) throw new Error(`audio download failed (${r.status})`); return r.arrayBuffer(); })
        .then((ab) => this.ctx.decodeAudioData(ab));
      p.catch(() => this.buffers.delete(key));   // let a later play retry
      this.buffers.set(key, p);
    }
    return this.buffers.get(key);
  }

  /** Preload everything the timeline will play; returns the number of failures (reported). */
  async preload(doc, chunks) {
    this._ensureCtx();
    const { placed } = layout(doc, chunks);
    const byId = Object.fromEntries(chunks.map((c) => [String(c.id), c]));
    const jobs = placed.map((p) => {
      const c = byId[p.chunk_id];
      return this._buffer(`c:${c.id}:${c.revision}`, () => this.loaders.chunkUrl(c));
    });
    for (const m of doc.music.clips) jobs.push(this._buffer(`m:${m.media_id}`, () => this.loaders.mediaUrl(m.media_id)));
    const res = await Promise.allSettled(jobs);
    const failed = res.filter((r) => r.status === "rejected");
    if (failed.length) this.onError?.(`${failed.length} audio clip(s) couldn't load: ${failed[0].reason?.message || failed[0].reason}`);
    return failed.length;
  }

  async play(doc, chunks, fromT = this.t) {
    this.stop();
    this._ensureCtx();
    await this.ctx.resume();
    await this.preload(doc, chunks);
    const end = durationT(doc);
    if (fromT >= end) fromT = 0;
    const now = this.ctx.currentTime + 0.12;
    this.startAt = now - fromT;
    this.doc = doc;
    this.playing = true;
    this.onState?.(true);
    this.master.gain.value = 1;

    const { placed } = layout(doc, chunks);
    const byId = Object.fromEntries(chunks.map((c) => [String(c.id), c]));
    const oa = doc.original_audio;
    const origBase = oa.muted ? 0 : dbToGain(oa.gain_db);
    const g = this.origGain.gain;
    g.cancelScheduledValues(0);
    g.setValueAtTime(origBase, now);

    for (const p of placed) {
      if (p.muted || p.t + p.length <= fromT || p.t >= end) continue;
      const c = byId[p.chunk_id];
      const buf = await this.buffers.get(`c:${c.id}:${c.revision}`)?.catch(() => null);
      if (!buf) continue;
      const skip = Math.max(0, fromT - p.t);
      const len = Math.min(p.length - skip, end - Math.max(p.t, fromT));
      if (len <= 0) continue;
      const src = this.ctx.createBufferSource();
      src.buffer = buf;
      const gain = this.ctx.createGain();
      gain.gain.value = dbToGain(p.gain_db + doc.voice.gain_db);
      src.connect(gain).connect(this.master);
      const when = this.startAt + Math.max(p.t, fromT);
      src.start(when, p.trim_in + skip, len);
      this.sources.push(src);
      if (oa.auto_duck && !oa.muted) {             // duck the original under the voice
        g.setTargetAtTime(origBase * 0.25, when - 0.05, 0.05);
        g.setTargetAtTime(origBase, when + len, 0.15);
      }
    }

    for (const m of doc.music.clips) {
      const buf = await this.buffers.get(`m:${m.media_id}`)?.catch(() => null);
      if (!buf) continue;
      const mlen = Math.min(m.media_out - m.media_in, end - m.t);
      if (m.t + mlen <= fromT || mlen <= 0) continue;
      const skip = Math.max(0, fromT - m.t);
      const src = this.ctx.createBufferSource();
      src.buffer = buf;
      const gain = this.ctx.createGain();
      const level = dbToGain(m.gain_db + doc.music.gain_db);
      const t0 = this.startAt + m.t;                // where the clip's own 0 sits
      gain.gain.setValueAtTime(m.fade_in > 0 ? 0 : level, Math.max(now, t0));
      if (m.fade_in > 0) gain.gain.linearRampToValueAtTime(level, t0 + m.fade_in);
      if (m.fade_out > 0) {
        gain.gain.setValueAtTime(level, t0 + mlen - m.fade_out);
        gain.gain.linearRampToValueAtTime(0, t0 + mlen);
      }
      src.connect(gain).connect(this.master);
      src.start(this.startAt + Math.max(m.t, fromT), m.media_in + skip, mlen - skip);
      this.sources.push(src);
    }

    this.clips = videoLayout(doc);
    this._seekVideo(fromT);
    this.video.play().catch((e) => this.onError?.(`Video can't play: ${e.message}`));
    this.timer = setInterval(() => this._tick(), TICK_MS);
  }

  _clipAt(t) {
    return this.clips.find((c) => t >= c.t && t < c.t + (c.src_out - c.src_in));
  }

  _seekVideo(t) {
    const c = this._clipAt(t);
    if (c) this.video.currentTime = c.src_in + (t - c.t);
  }

  _tick() {
    const t = this.ctx.currentTime - this.startAt;
    if (t >= durationT(this.doc)) { this.stop(); this.t = 0; this.onTime?.(0); return; }
    if (t < 0) return;
    this.t = t;
    const c = this._clipAt(t);
    if (c) {
      const want = c.src_in + (t - c.t);
      if (Math.abs(this.video.currentTime - want) > DRIFT_S) this.video.currentTime = want;   // cut or drift
    }
    this.onTime?.(t);
  }

  stop() {
    clearInterval(this.timer);
    for (const s of this.sources) { try { s.stop(); } catch { /* not started yet */ } }
    this.sources = [];
    if (this.origGain) { this.origGain.gain.cancelScheduledValues(0); }
    this.video?.pause();
    if (this.playing) this.onState?.(false);
    this.playing = false;
  }

  seek(doc, t) {
    this.t = Math.max(0, Math.min(t, durationT(doc)));
    this.clips = videoLayout(doc);
    this._seekVideo(this.t);
    this.onTime?.(this.t);
  }

  /** A regenerated chunk: drop its old buffer so the next play loads the new audio. */
  invalidate(chunkId) {
    for (const k of this.buffers.keys()) if (k.startsWith(`c:${chunkId}:`)) this.buffers.delete(k);
  }

  dispose() {
    this.stop();
    this.ctx?.close();
  }
}
