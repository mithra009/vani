// Multi-track timeline editor (R6, R7, D2–D6, D9, D11), laid out like a pro NLE (Premiere Pro's
// Editing workspace): Effect Controls + Program monitor on top, the Timeline panel below with a
// tool strip, track headers (V1 / A1–A3 / C1), a ruler and a draggable playhead.
// Edits apply locally at once with undo/redo + autosave; preview is live Web Audio.
import { useEffect, useMemo, useRef, useState } from "react";
import { Loader } from "./Icons.jsx";
import * as editor from "../lib/editorApi.js";
import { uploadToStorage } from "../lib/libraryStore.js";
import { api } from "../lib/api.js";
import { durationT, layout, videoLayout } from "../lib/timeline.js";
import { useTimeline } from "../lib/useTimeline.js";
import { PreviewEngine } from "../lib/preview.js";
import { clock } from "../lib/format.js";

const FLAG_TEXT = {
  overlap: "Overlaps another voice clip", past_end: "Runs past the end of the video (cut at export)",
  before_start: "Starts before 0 (cut at export)", on_cut: "Speech runs into a video cut",
};
const HIDDEN_TEXT = { video_cut: "its video was cut", no_audio: "no audio yet", unplaced: "not placed" };
const ZOOM_MIN = 4, ZOOM_MAX = 200;
const TAIL_PX = 48;                 // empty lane after the end, room to drop a clip past it
const STEP_S = 0.1;                       // ← / → nudge; Shift for 1 s
const TOP_KEY = "vani.editor.topHeight";
const TRACKS = 5, RULER_H = 22, ROW_MIN = 18, ROW_MAX = 26;

/** 00:00:12.04 — hours:minutes:seconds.hundredths (the source frame rate isn't known here). */
export function timecode(s) {
  const cs = Math.max(0, Math.round(s * 100));
  const h = Math.floor(cs / 360000), m = Math.floor(cs / 6000) % 60, sec = Math.floor(cs / 100) % 60, c = cs % 100;
  const p = (n) => String(n).padStart(2, "0");
  return `${p(h)}:${p(m)}:${p(sec)}.${p(c)}`;
}

export default function TimelineEditor({ project, chunks }) {
  const [media, setMedia] = useState([]);
  const ctx = useMemo(() => ({
    sourceS: Number(project.duration_s || 0),
    chunkIds: new Set(chunks.map((c) => String(c.id))),
    media: Object.fromEntries(media.map((m) => [String(m.id), Number(m.duration_s)])),
  }), [project.duration_s, chunks, media]);
  const tl = useTimeline(project.id, ctx);

  const [zoom, setZoom] = useState(40);                  // px per second
  const [tool, setTool] = useState("select");            // select | razor
  const [sel, setSel] = useState(null);                  // {kind, id}
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [loadingPlay, setLoadingPlay] = useState(false);
  const [err, setErr] = useState(null);
  const [proxyUrl, setProxyUrl] = useState(null);
  const [topH, setTopH] = useState(() => {
    // A saved height from a taller window could swallow the timeline: keep it within 60% of this one.
    try {
      const h = Number(localStorage.getItem(TOP_KEY));
      return h ? Math.min(h, Math.round(window.innerHeight * 0.6)) : null;
    } catch { return null; }
  });
  const videoRef = useRef(null);
  const engine = useRef(null);
  const scrollRef = useRef(null);
  const bodyRef = useRef(null);
  // Track height follows the panel: the five rows always fit without a vertical scrollbar.
  const [rowH, setRowH] = useState(30);
  useEffect(() => {
    const el = bodyRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const fit = () => {
      const sc = scrollRef.current;
      const hBar = sc ? sc.offsetHeight - sc.clientHeight : 0;          // horizontal scrollbar, if shown
      const avail = el.clientHeight - RULER_H - hBar - 2;
      setRowH(Math.max(ROW_MIN, Math.min(ROW_MAX, Math.floor(avail / TRACKS))));
    };
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    fit();
    return () => ro.disconnect();
  }, [tl.status]);
  const musicInput = useRef(null);

  useEffect(() => {
    editor.getTimeline(project.id).then((r) => setMedia(r.media || [])).catch((e) => setErr(e.message));
    api.assetPreviewUrl(project.asset_id)
      .then((r) => setProxyUrl(r.url))
      .catch((e) => setErr(`Preview video unavailable: ${e.message}`));
  }, [project.id, project.asset_id]);

  useEffect(() => {
    if (!videoRef.current) return;
    engine.current = new PreviewEngine(videoRef.current, {
      chunkUrl: (c) => editor.chunkAudioUrl(project.id, c.id).then((r) => r.url),
      mediaUrl: (id) => editor.mediaUrl(project.id, id).then((r) => r.url),
    }, setT, setErr, setPlaying);
    return () => engine.current?.dispose();
  }, [project.id, proxyUrl, tl.status]);

  // Regenerated chunks: drop stale buffers.
  const revs = useRef({});
  useEffect(() => {
    for (const c of chunks) {
      if (revs.current[c.id] !== undefined && revs.current[c.id] !== c.revision) engine.current?.invalidate(c.id);
      revs.current[c.id] = c.revision;
    }
  }, [chunks]);

  // A just-uploaded music file is placed once it is part of the validation context.
  const [pendingMusic, setPendingMusic] = useState(null);
  useEffect(() => {
    if (pendingMusic && ctx.media[pendingMusic.id] && tl.status === "ready") {
      tl.run([{ type: "music.add", clip: { media_id: pendingMusic.id, t: pendingMusic.t } }]);
      setPendingMusic(null);
    }
  }, [pendingMusic, ctx, tl]);

  // Keyboard, NLE-style. Ignored while typing in a field.
  useEffect(() => {
    const onKey = (e) => {
      if (tl.status !== "ready" || /input|textarea|select/i.test(e.target.tagName)) return;
      const k = e.key.toLowerCase();
      const mod = e.ctrlKey || e.metaKey;
      if (mod && k === "z") { e.preventDefault(); e.shiftKey ? tl.redo() : tl.undo(); return; }
      if (mod && k === "y") { e.preventDefault(); tl.redo(); return; }
      if (mod) return;
      if (e.key === " " || k === "k") { e.preventDefault(); togglePlay(); }
      else if (k === "v") setTool("select");
      else if (k === "c") setTool("razor");
      else if (e.key === "Home") { e.preventDefault(); seek(0); }
      else if (e.key === "End") { e.preventDefault(); seek(end); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); seek(t - (e.shiftKey ? 1 : STEP_S)); }
      else if (e.key === "ArrowRight") { e.preventDefault(); seek(t + (e.shiftKey ? 1 : STEP_S)); }
      else if (e.key === "=" || e.key === "+") setZoom((z) => Math.min(ZOOM_MAX, z * 1.25));
      else if (e.key === "-") setZoom((z) => Math.max(ZOOM_MIN, z / 1.25));
      else if (e.key === "\\") fitZoom();
      else if (e.key === "Delete" || e.key === "Backspace") deleteSelected();
      else if (e.key === "Escape") setSel(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // Open zoomed to fit the whole timeline (once; after that the user's zoom is kept).
  const fitted = useRef(false);
  useEffect(() => {
    if (fitted.current || !tl.doc || !scrollRef.current) return;
    fitted.current = true;
    const w = scrollRef.current.clientWidth || 900;
    setZoom(Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, (w - TAIL_PX) / Math.max(1, durationT(tl.doc)))));
  }, [tl.doc]);

  if (tl.status === "loading") return <div className="pp pp-loading"><Loader size={36} /></div>;
  if (tl.status === "error") return <div className="banner error" role="alert"><span className="banner-dot" />Timeline failed to load: {tl.error}</div>;

  const doc = tl.doc;
  const end = durationT(doc);
  const vl = videoLayout(doc);
  const { placed, hidden } = layout(doc, chunks);
  const byId = Object.fromEntries(chunks.map((c) => [String(c.id), c]));
  const width = Math.max(240, end * zoom + TAIL_PX);
  const audible = placed.filter((p) => !p.muted);
  const caption = doc.captions.enabled ? audible.find((p) => t >= p.t && t < p.t + p.length) : null;
  const mediaName = (id) => media.find((x) => String(x.id) === id)?.filename || "audio";

  async function togglePlay() {
    if (!engine.current || loadingPlay) return;
    if (playing) { engine.current.stop(); return; }
    setErr(null);
    setLoadingPlay(true);
    try { await engine.current.play(doc, chunks, t >= end ? 0 : t); }
    catch (e) { setErr(`Preview failed: ${e.message}`); engine.current.stop(); }
    finally { setLoadingPlay(false); }
  }

  /** Move the playhead; if it was playing, keep playing from the new spot. */
  function seek(x, { resume = false } = {}) {
    const to = Math.max(0, Math.min(x, end));
    engine.current?.stop();
    engine.current?.seek(doc, to);
    setT(to);
    if (resume) engine.current?.play(doc, chunks, to).catch((e) => setErr(`Preview failed: ${e.message}`));
  }

  function fitZoom() {
    const w = scrollRef.current?.clientWidth || 900;
    setZoom(Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, (w - TAIL_PX) / Math.max(1, end))));
  }

  function razorVideoAt(c, at) {
    if (at <= c.t + 0.05 || at >= c.t + (c.src_out - c.src_in) - 0.05) return;
    tl.run([{ type: "video.split", clip_id: c.id, at_src: round3(c.src_in + (at - c.t)) }]);
  }

  function razorMusicAt(m, at) {
    const cut = round3(m.media_in + (at - m.t));
    if (cut <= m.media_in + 0.05 || cut >= m.media_out - 0.05) return;
    // Two ops, one undo step: shorten this clip, add the remainder as a new clip right after it.
    tl.run([
      { type: "music.set", clip_id: m.id, fields: { media_out: cut, fade_out: 0 } },
      { type: "music.add", clip: { media_id: m.media_id, t: round3(m.t + (cut - m.media_in)), media_in: cut,
        media_out: m.media_out, fade_in: 0, fade_out: m.fade_out, gain_db: m.gain_db } },
    ]);
  }

  async function razorVoiceAt(p, at) {
    // Voice is text: split the chunk's text at the word nearest the cut, then both halves are re-voiced.
    const c = byId[p.chunk_id];
    if (!c || c.status !== "ready") { setErr("Wait for this chunk's voice to finish before splitting it."); return; }
    const frac = (at - p.t) / Math.max(0.01, p.length);
    const target = Math.round(c.text.length * frac);
    const spaces = [...c.text.matchAll(/\s/g)].map((m) => m.index).filter((i) => i > 0 && i < c.text.length - 1);
    if (!spaces.length) { setErr("This chunk is a single word and can't be split."); return; }
    const at_char = spaces.reduce((a, b) => (Math.abs(b - target) < Math.abs(a - target) ? b : a)) + 1;
    try { await editor.splitChunk(project.id, c.id, c.revision, at_char); setSel(null); }
    catch (e) { setErr(`Couldn't split: ${e.message}`); }
  }

  function deleteSelected() {
    if (!sel) return;
    if (sel.kind === "video" && doc.video.length > 1) { tl.run([{ type: "video.delete", clip_id: sel.id }]); setSel(null); }
    else if (sel.kind === "music") { tl.run([{ type: "music.delete", clip_id: sel.id }]); setSel(null); }
  }

  function startResize(e) {
    const panel = e.currentTarget.previousElementSibling;
    const startY = e.clientY, startH = panel.getBoundingClientRect().height;
    const move = (ev) => setTopH(Math.max(220, Math.min(window.innerHeight * 0.6, startH + ev.clientY - startY)));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setTopH((h) => { try { localStorage.setItem(TOP_KEY, String(Math.round(h))); } catch { /* optional */ } return h; });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  async function addMusic(f) {
    if (!f) return;
    setErr(null);
    try {
      const duration = await audioDuration(f);
      const init = await editor.mediaInit(project.id, f.name, duration);
      await uploadToStorage(f, init.uploadUrl, () => {}, init.uploadMethod);
      const m = await editor.mediaComplete(project.id, init.media.id);
      setMedia((ms) => [...ms, m]);
      setPendingMusic({ id: String(m.id), t: round3(t) });
    } catch (e) {
      setErr(`Music upload failed: ${e.message}`);
    } finally {
      if (musicInput.current) musicInput.current.value = "";
    }
  }

  const razor = tool === "razor";
  return (
    <div className={`pp ${razor ? "pp-razor" : ""} ${rowH < 24 ? "pp-rows-tight" : ""} ${topH ? "" : "pp-auto"}`} style={{ "--pp-row-h": `${rowH}px` }}>
      {/* ───────────────────────── top: Effect Controls | Program monitor ───────────────────────── */}
      <div className="pp-top" style={topH ? { height: topH } : undefined}>
        <section className="pp-panel pp-controls" aria-label="Effect Controls">
          <header className="pp-head"><span className="pp-tab">Effect Controls</span></header>
          <div className="pp-body">
            <Inspector sel={sel} setSel={setSel} doc={doc} tl={tl} placed={placed} byId={byId} chunks={chunks}
                       project={project} media={media} setErr={setErr} />
          </div>
        </section>

        <section className="pp-panel pp-program" aria-label="Program monitor">
          <header className="pp-head">
            <span className="pp-tab">Program: <b>{project.name}</b></span>
            <SaveState save={tl.save} />
          </header>
          <div className="pp-monitor">
            {proxyUrl
              ? <video ref={videoRef} src={proxyUrl} crossOrigin="anonymous" playsInline preload="auto" className="pp-video"
                       onError={() => setErr("The preview video failed to load (the link may have expired; reload the page).")} />
              : <div className="pp-video pp-video-empty"><Loader size={24} /> Preview video is still processing…</div>}
            {caption && <div className="pp-caption">{byId[caption.chunk_id]?.text}</div>}
          </div>
          <div className="pp-transport">
            <span className="pp-tc pp-tc-now" title="Playhead position (hours:minutes:seconds.hundredths)">{timecode(t)}</span>
            <div className="pp-transport-btns" role="group" aria-label="Transport">
              <TBtn label="Go to start (Home)" onClick={() => seek(0)}><path d="M6 5v14M18 6l-9 6 9 6z" /></TBtn>
              <TBtn label="Step back (←)" onClick={() => seek(t - 1)}><path d="M11 6l-7 6 7 6zM20 6l-7 6 7 6z" /></TBtn>
              <button className="pp-play" onClick={togglePlay} disabled={!proxyUrl || loadingPlay}
                      aria-label={playing ? "Pause (Space)" : "Play (Space)"} title={playing ? "Pause (Space)" : "Play (Space)"}>
                {loadingPlay ? <Loader size={14} /> : playing
                  ? <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true"><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></svg>
                  : <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13l10.5-6.5z" /></svg>}
              </button>
              <TBtn label="Step forward (→)" onClick={() => seek(t + 1)}><path d="M13 6l7 6-7 6zM4 6l7 6-7 6z" /></TBtn>
              <TBtn label="Go to end (End)" onClick={() => seek(end)}><path d="M18 5v14M6 6l9 6-9 6z" /></TBtn>
            </div>
            <span className="pp-tc pp-tc-dur" title="Sequence duration">{timecode(end)}</span>
          </div>
        </section>
      </div>

      <div className="pp-splitter" role="separator" aria-orientation="horizontal" aria-label="Resize monitor and timeline"
           onPointerDown={startResize} title="Drag to resize" />

      {/* ───────────────────────────────── bottom: Timeline panel ───────────────────────────────── */}
      <section className="pp-panel pp-timeline" aria-label="Timeline">
        <header className="pp-head pp-tl-head">
          <span className="pp-tab">Timeline</span>
          <span className="pp-tc pp-tc-big">{timecode(t)}</span>
          <div className="pp-tl-actions">
            <IconBtn label="Undo (Ctrl+Z)" onClick={tl.undo} disabled={!tl.canUndo}><path d="M9 7H5V3M5.5 7A8 8 0 1 1 4 13" /></IconBtn>
            <IconBtn label="Redo (Ctrl+Shift+Z)" onClick={tl.redo} disabled={!tl.canRedo}><path d="M15 7h4V3M18.5 7A8 8 0 1 0 20 13" /></IconBtn>
            <span className="pp-sep" />
            <button className={`pp-toggle ${doc.captions.enabled ? "on" : ""}`} aria-pressed={doc.captions.enabled}
                    onClick={() => tl.run([{ type: "track.set", track: "captions", fields: { enabled: !doc.captions.enabled } }])}
                    title="Show captions in the preview and enable them for export">CC</button>
            <input ref={musicInput} type="file" accept=".mp3,.wav,.m4a,.aac,.ogg,.flac,audio/*" hidden onChange={(e) => addMusic(e.target.files[0])} />
            <button className="pp-text-btn" onClick={() => musicInput.current?.click()} title="Add a music file at the playhead">+ Music</button>
          </div>
          <div className="pp-zoom" role="group" aria-label="Zoom">
            <IconBtn label="Zoom out (−)" onClick={() => setZoom((z) => Math.max(ZOOM_MIN, z / 1.25))}><path d="M5 12h14" /></IconBtn>
            <input type="range" min={ZOOM_MIN} max={ZOOM_MAX} value={Math.round(zoom)} onChange={(e) => setZoom(+e.target.value)}
                   aria-label="Zoom level" />
            <IconBtn label="Zoom in (+)" onClick={() => setZoom((z) => Math.min(ZOOM_MAX, z * 1.25))}><path d="M5 12h14M12 5v14" /></IconBtn>
            <button className="pp-text-btn" onClick={fitZoom} title="Fit the sequence in view (\)">Fit</button>
          </div>
        </header>

        {(err || tl.notices.length > 0) && (
          <div className="pp-msgs">
            {err && <div className="pp-msg pp-msg-err" role="alert"><span>{err}</span><button onClick={() => setErr(null)} aria-label="Dismiss">×</button></div>}
            {tl.notices.map((n) => (
              <div key={n.id} className="pp-msg" role="status"><span>{n.msg}</span><button onClick={() => tl.dismiss(n.id)} aria-label="Dismiss">×</button></div>
            ))}
          </div>
        )}

        <div className="pp-tl-body" ref={bodyRef}>
          <div className="pp-tools" role="toolbar" aria-label="Tools" aria-orientation="vertical">
            <button className={`pp-tool ${tool === "select" ? "on" : ""}`} aria-pressed={tool === "select"} onClick={() => setTool("select")}
                    title="Selection tool (V): select, drag and trim clips">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true"><path d="M6 3l12 9-5.2.9 3 6.3-2.4 1.1-3-6.3L6 18z" /></svg>
            </button>
            <button className={`pp-tool ${razor ? "on" : ""}`} aria-pressed={razor} onClick={() => setTool("razor")}
                    title="Razor tool (C): click a clip to cut it there">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden="true"><circle cx="6" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><path d="M8.6 7.6L20 18M8.6 16.4L20 6" /></svg>
            </button>
          </div>

          <div className="pp-headers">
            <div className="pp-corner" />
            <TrackHeader id="V1" name="Video" kind="video" />
            <TrackHeader id="A1" name="Original" kind="audio" selected={sel?.kind === "original"} onSelect={() => setSel({ kind: "original" })}
                         toggle={{ label: "M", on: doc.original_audio.muted, title: doc.original_audio.muted ? "Unmute the original audio" : "Mute the original audio",
                                   onClick: () => tl.run([{ type: "track.set", track: "original_audio", fields: { muted: !doc.original_audio.muted } }]) }} />
            <TrackHeader id="A2" name="Voice" kind="audio" selected={sel?.kind === "voiceTrack"} onSelect={() => setSel({ kind: "voiceTrack" })} />
            <TrackHeader id="A3" name="Music" kind="audio" selected={sel?.kind === "musicTrack"} onSelect={() => setSel({ kind: "musicTrack" })} />
            <TrackHeader id="C1" name="Captions" kind="caption"
                         toggle={{ label: "CC", on: doc.captions.enabled, title: doc.captions.enabled ? "Turn captions off" : "Turn captions on",
                                   onClick: () => tl.run([{ type: "track.set", track: "captions", fields: { enabled: !doc.captions.enabled } }]) }} />
          </div>

          <div className="pp-scroll" ref={scrollRef}>
            <div className="pp-lanes" style={{ width }}>
              <Ruler end={end} zoom={zoom} onSeek={seek} playing={playing} />
              <Playhead t={t} zoom={zoom} onSeek={seek} playing={playing} />

              <Lane kind="video">
                {vl.map((c, i) => (
                  <VideoClip key={c.id} c={c} i={i} n={vl.length} next={vl[i + 1]} zoom={zoom} selected={sel?.id === c.id}
                             razor={razor} onRazor={(at) => razorVideoAt(c, at)}
                             onSelect={() => setSel({ kind: "video", id: c.id })} tl={tl} sourceS={ctx.sourceS} />
                ))}
              </Lane>

              <Lane kind="audio" muted={doc.original_audio.muted}>
                <div className={`pp-clip pp-clip-orig ${sel?.kind === "original" ? "sel" : ""}`} style={{ left: 0, width: end * zoom }}
                     onPointerDown={() => setSel({ kind: "original" })}>
                  <span className="pp-clip-name">{doc.original_audio.muted ? "Original audio · muted"
                    : `Original audio · ${doc.original_audio.gain_db} dB${doc.original_audio.auto_duck ? " · ducks under voice" : ""}`}</span>
                </div>
              </Lane>

              <Lane kind="audio">
                {placed.map((p) => (
                  <DragClip key={p.chunk_id} left={p.t * zoom} width={Math.max(4, p.length * zoom)} zoom={zoom}
                            razor={razor} onRazor={(at) => razorVoiceAt(p, at)}
                            className={`pp-clip pp-clip-voice ${p.flags.length ? "flagged" : ""} ${p.muted ? "muted" : ""} ${sel?.id === p.chunk_id ? "sel" : ""}`}
                            title={[byId[p.chunk_id]?.text, ...p.flags.map((f) => `⚠ ${FLAG_TEXT[f]}`)].join("\n")}
                            onSelect={() => setSel({ kind: "voice", id: p.chunk_id })}
                            onDrop={(dt) => {
                              const vc = doc.voice.clips[p.chunk_id] || {};
                              const fields = vc.detached_t != null
                                ? { detached_t: round3(Math.max(0, vc.detached_t + dt)) }
                                : { offset: round3((vc.offset || 0) + dt) };
                              tl.run([{ type: "voice.set", chunk_id: p.chunk_id, fields }]);
                            }}>
                    <span className="pp-clip-name">{p.flags.length > 0 && <span className="pp-flag" aria-label="Has warnings">⚠ </span>}
                      {byId[p.chunk_id]?.text}</span>
                  </DragClip>
                ))}
              </Lane>

              <Lane kind="audio">
                {doc.music.clips.map((m) => (
                  <DragClip key={m.id} left={m.t * zoom} width={Math.max(4, (m.media_out - m.media_in) * zoom)} zoom={zoom}
                            razor={razor} onRazor={(at) => razorMusicAt(m, at)}
                            className={`pp-clip pp-clip-music ${sel?.id === m.id ? "sel" : ""}`}
                            onSelect={() => setSel({ kind: "music", id: m.id })}
                            onDrop={(dt) => tl.run([{ type: "music.set", clip_id: m.id, fields: { t: round3(Math.max(0, m.t + dt)) } }])}>
                    {m.fade_in > 0 && <span className="pp-fade in" style={{ width: m.fade_in * zoom }} />}
                    <span className="pp-clip-name">{mediaName(m.media_id)}</span>
                    {m.fade_out > 0 && <span className="pp-fade out" style={{ width: m.fade_out * zoom }} />}
                  </DragClip>
                ))}
              </Lane>

              <Lane kind="caption" muted={!doc.captions.enabled}>
                {doc.captions.enabled
                  ? audible.map((p) => (
                    <div key={p.chunk_id} className="pp-clip pp-clip-caption" style={{ left: p.t * zoom, width: Math.max(4, p.length * zoom) }}
                         title={byId[p.chunk_id]?.text} onPointerDown={() => setSel({ kind: "voice", id: p.chunk_id })}>
                      <span className="pp-clip-name">{byId[p.chunk_id]?.text}</span>
                    </div>))
                  : <span className="pp-lane-note">Captions are off. Turn them on with CC.</span>}
              </Lane>
            </div>
          </div>
        </div>

        <footer className="pp-status">
          <span>{razor ? "Razor: click a clip to cut it. Voice clips split at the nearest word and are re-voiced." : "Selection: drag clips to move them, drag video edges to trim."}</span>
          {hidden.length > 0 && (
            <span className="pp-status-warn">
              Not on the timeline: {hidden.map((h) => `#${(byId[h.chunk_id]?.idx ?? 0) + 1} (${HIDDEN_TEXT[h.reason]})`).join(", ")}
            </span>
          )}
          <span className="pp-keys">Space play · V select · C razor · ← → nudge · Del delete · \ fit</span>
        </footer>
      </section>
    </div>
  );
}

const round3 = (x) => Math.round(x * 1000) / 1000;

const Svg = ({ children, size = 16 }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);
function IconBtn({ label, onClick, disabled, children }) {
  return <button className="pp-icon" onClick={onClick} disabled={disabled} aria-label={label} title={label}><Svg>{children}</Svg></button>;
}
function TBtn({ label, onClick, children }) {
  return <button className="pp-tbtn" onClick={onClick} aria-label={label} title={label}><Svg size={18}>{children}</Svg></button>;
}

function SaveState({ save }) {
  const label = { saved: "All changes saved", saving: "Saving…", retrying: "Not saved, retrying…", error: "Not saved" }[save.state];
  return (
    <span className={`pp-save pp-save-${save.state}`} role="status" aria-live="polite" title={save.message || ""}>
      <span className="pp-save-dot" aria-hidden="true" />{label}
    </span>
  );
}

function TrackHeader({ id, name, kind, selected, onSelect, toggle }) {
  return (
    <div className={`pp-th pp-th-${kind} ${selected ? "sel" : ""} ${onSelect ? "clickable" : ""}`}
         onClick={onSelect} role={onSelect ? "button" : undefined} tabIndex={onSelect ? 0 : undefined}
         onKeyDown={(e) => { if (onSelect && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onSelect(); } }}
         title={onSelect ? `${name} track: click to adjust its level` : undefined}>
      <span className="pp-th-id">{id}</span>
      <span className="pp-th-name">{name}</span>
      {toggle && (
        <button className={`pp-th-btn ${toggle.on ? "on" : ""}`} aria-pressed={toggle.on} title={toggle.title}
                onClick={(e) => { e.stopPropagation(); toggle.onClick(); }}>{toggle.label}</button>
      )}
    </div>
  );
}

/** Seek by dragging: pointer x inside the lanes to seconds. Resumes playback on release if it was playing. */
function useScrub(zoom, onSeek, playing) {
  const wasPlaying = useRef(false);
  const at = (e) => (e.clientX - e.currentTarget.closest(".pp-lanes").getBoundingClientRect().left) / zoom;
  return {
    onPointerDown: (e) => {
      e.preventDefault();
      wasPlaying.current = playing;
      e.currentTarget.setPointerCapture(e.pointerId);
      onSeek(at(e));
    },
    onPointerMove: (e) => { if (e.currentTarget.hasPointerCapture(e.pointerId)) onSeek(at(e)); },
    onPointerUp: (e) => onSeek(at(e), { resume: wasPlaying.current }),
  };
}

function Playhead({ t, zoom, onSeek, playing }) {
  const scrub = useScrub(zoom, onSeek, playing);
  return (
    <div className="pp-playhead" style={{ left: t * zoom }}>
      <span className="pp-playhead-cap" {...scrub} title="Drag to move the playhead" />
    </div>
  );
}

function Lane({ kind, muted, children }) {
  return <div className={`pp-lane pp-lane-${kind} ${muted ? "muted" : ""}`}>{children}</div>;
}

function Ruler({ end, zoom, onSeek, playing }) {
  const scrub = useScrub(zoom, onSeek, playing);
  // Major ticks with labels about every 80 px; minor ticks between them.
  const steps = [0.5, 1, 2, 5, 10, 15, 30, 60];
  const major = steps.find((s) => s * zoom >= 80) || 60;
  const minor = major / (major >= 5 ? 5 : 2);
  const ticks = [];
  for (let s = 0; s <= end + 1e-6; s += minor) {
    const isMajor = Math.abs(s / major - Math.round(s / major)) < 1e-6;
    ticks.push(<span key={s.toFixed(3)} className={`pp-tick ${isMajor ? "major" : ""}`} style={{ left: s * zoom }}>
      {isMajor && <span className="pp-tick-label">{major < 1 ? s.toFixed(1) : clock(s)}</span>}
    </span>);
  }
  return <div className="pp-ruler" {...scrub}>{ticks}<span className="pp-ruler-end" style={{ left: end * zoom }} /></div>;
}

/** A clip you can click to select and drag horizontally (one op on release); with the razor, a click cuts it. */
function DragClip({ left, width, zoom, className, title, onSelect, onDrop, razor, onRazor, children }) {
  const [dx, setDx] = useState(0);
  const start = useRef(null);
  const atTime = (e) => (e.clientX - e.currentTarget.closest(".pp-lanes").getBoundingClientRect().left) / zoom;
  return (
    <div className={className} title={title} style={{ left: left + dx, width }}
         onPointerDown={(e) => {
           if (razor) { e.stopPropagation(); onRazor(atTime(e)); return; }
           e.currentTarget.setPointerCapture(e.pointerId); start.current = e.clientX; onSelect();
         }}
         onPointerMove={(e) => { if (start.current != null) setDx(e.clientX - start.current); }}
         onPointerUp={() => {
           if (start.current == null) return;
           const moved = dx;
           start.current = null; setDx(0);
           if (Math.abs(moved) > 2) onDrop(moved / zoom);
         }}>
      {children}
    </div>
  );
}

function VideoClip({ c, i, n, next, zoom, selected, onSelect, tl, sourceS, razor, onRazor }) {
  // Joinable: the next clip continues exactly where this one ends in the source (an undone cut).
  const joinable = next && Math.abs(next.src_in - c.src_out) < 1e-3;
  const len = c.src_out - c.src_in;
  const [trim, setTrim] = useState(null);     // {side, dx}
  const startX = useRef(0);
  const handle = (side) => ({
    onPointerDown: (e) => {
      if (razor) return;
      e.stopPropagation(); e.currentTarget.setPointerCapture(e.pointerId); startX.current = e.clientX; setTrim({ side, dx: 0 });
    },
    onPointerMove: (e) => trim && setTrim({ side, dx: e.clientX - startX.current }),
    onPointerUp: () => {
      if (!trim) return;
      const ds = trim.dx / zoom;
      setTrim(null);
      if (Math.abs(trim.dx) < 2) return;
      const src_in = side === "in" ? Math.max(0, c.src_in + ds) : c.src_in;
      const src_out = side === "out" ? Math.min(sourceS, c.src_out + ds) : c.src_out;
      tl.run([{ type: "video.trim", clip_id: c.id, src_in: round3(src_in), src_out: round3(src_out) }]);
    },
  });
  const dl = trim?.side === "in" ? trim.dx : 0;
  const dw = trim ? (trim.side === "in" ? -trim.dx : trim.dx) : 0;
  const act = (e, ops) => { e.stopPropagation(); tl.run(ops); };
  return (
    <div className={`pp-clip pp-clip-video ${selected ? "sel" : ""}`} style={{ left: c.t * zoom + dl, width: Math.max(6, len * zoom + dw) }}
         title={`Source ${clock(c.src_in)}–${clock(c.src_out)}`}
         onPointerDown={(e) => {
           if (razor) onRazor((e.clientX - e.currentTarget.closest(".pp-lanes").getBoundingClientRect().left) / zoom);
           else onSelect();
         }}>
      <span className="pp-handle in" {...handle("in")} />
      <span className="pp-clip-name">Video · {clock(c.src_in)}–{clock(c.src_out)}</span>
      {selected && !razor && (
        <span className="pp-clip-actions">
          {i > 0 && <button onPointerDown={(e) => e.stopPropagation()} onClick={(e) => act(e, [{ type: "video.move", clip_id: c.id, index: i - 1 }])} title="Move earlier" aria-label="Move earlier">◀</button>}
          {i < n - 1 && <button onPointerDown={(e) => e.stopPropagation()} onClick={(e) => act(e, [{ type: "video.move", clip_id: c.id, index: i + 1 }])} title="Move later" aria-label="Move later">▶</button>}
          {joinable && <button onPointerDown={(e) => e.stopPropagation()} onClick={(e) => act(e, [{ type: "video.join", clip_id: c.id, next_id: next.id }])} title="Join with the next clip" aria-label="Join with the next clip">⊕</button>}
          {n > 1 && <button onPointerDown={(e) => e.stopPropagation()} onClick={(e) => act(e, [{ type: "video.delete", clip_id: c.id }])} title="Delete (voice in it disappears)" aria-label="Delete clip">✕</button>}
        </span>
      )}
      <span className="pp-handle out" {...handle("out")} />
    </div>
  );
}

// Module-level so it keeps its identity across renders (inputs inside must not remount mid-edit).
function Section({ title, children }) {
  return <section className="pp-sec"><h4 className="pp-sec-title">{title}</h4>{children}</section>;
}

function Inspector({ sel, setSel, doc, tl, placed, byId, chunks, project, media, setErr }) {
  const [busy, setBusy] = useState(false);
  if (!sel) {
    return (
      <div className="pp-empty">
        <p>No clip selected.</p>
        <p className="dim">Select a clip or a track header to adjust it. Use the razor (C) to cut clips.</p>
      </div>
    );
  }
  const num = (label, value, onCommit, { min, max, step = 0.05, unit } = {}) => (
    <label className="pp-field">
      <span className="pp-field-label">{label}</span>
      <span className="pp-field-input">
        <input type="number" defaultValue={value} key={`${label}${value}`} min={min} max={max} step={step}
               onBlur={(e) => { const v = parseFloat(e.target.value); if (Number.isFinite(v) && v !== value) onCommit(v); }}
               onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
        {unit && <span className="pp-unit">{unit}</span>}
      </span>
    </label>
  );
  const check = (label, checked, onChange, title) => (
    <label className="pp-check" title={title}><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} /> {label}</label>
  );

  if (sel.kind === "original") {
    const oa = doc.original_audio;
    const set = (fields) => tl.run([{ type: "track.set", track: "original_audio", fields }]);
    return (
      <>
        <div className="pp-subject"><span className="pp-chip pp-chip-audio">A1</span> Original audio</div>
        <Section title="Volume">
          {num("Level", oa.gain_db, (v) => set({ gain_db: v }), { min: -60, max: 12, step: 1, unit: "dB" })}
          {check("Mute", oa.muted, (v) => set({ muted: v }))}
          {check("Duck under the voice", oa.auto_duck, (v) => set({ auto_duck: v }))}
        </Section>
      </>
    );
  }

  if (sel.kind === "voiceTrack" || sel.kind === "musicTrack") {
    const track = sel.kind === "voiceTrack" ? "voice" : "music";
    return (
      <>
        <div className="pp-subject"><span className="pp-chip pp-chip-audio">{track === "voice" ? "A2" : "A3"}</span> {track === "voice" ? "Voice" : "Music"} track</div>
        <Section title="Volume">
          {num("Track level", doc[track].gain_db, (v) => tl.run([{ type: "track.set", track, fields: { gain_db: v } }]), { min: -60, max: 12, step: 1, unit: "dB" })}
          <p className="pp-note">Applies to every clip on this track, on top of each clip's own level.</p>
        </Section>
      </>
    );
  }

  if (sel.kind === "voice") {
    const c = byId[sel.id];
    const p = placed.find((x) => x.chunk_id === sel.id);
    if (!c) return null;
    const vc = { offset: 0, trim_in: 0, trim_out: 0, gain_db: 0, muted: false, detached_t: null, ...(doc.voice.clips[sel.id] || {}) };
    const set = (fields) => tl.run([{ type: "voice.set", chunk_id: sel.id, fields }]);
    const next = chunks.find((x) => x.idx === c.idx + 1);
    async function contentOp(fn) {
      setBusy(true); setErr(null);
      try { await fn(); } catch (e) { setErr(e.message); }
      setBusy(false);
    }
    return (
      <>
        <div className="pp-subject"><span className="pp-chip pp-chip-voice">A2</span> Voice · chunk {c.idx + 1}</div>
        <p className="pp-quote">{c.text}</p>
        {p?.flags.map((f) => <p key={f} className="pp-warn">⚠ {FLAG_TEXT[f]}</p>)}
        <Section title="Timing">
          {vc.detached_t == null
            ? num("Offset", vc.offset, (v) => set({ offset: v }), { min: -30, max: 30, unit: "s" })
            : num("Position", vc.detached_t, (v) => set({ detached_t: v }), { min: 0, unit: "s" })}
          {num("Cut from start", vc.trim_in, (v) => set({ trim_in: v }), { min: 0, unit: "s" })}
          {num("Cut from end", vc.trim_out, (v) => set({ trim_out: v }), { min: 0, unit: "s" })}
          <p className="pp-note">
            Plays {(Math.max(0, Number(c.audio_duration_s || 0) - vc.trim_in - vc.trim_out)).toFixed(2)} s of {Number(c.audio_duration_s || 0).toFixed(2)} s.
          </p>
          {check("Detach from video", vc.detached_t != null, (v) => set({ detached_t: v ? round3(p ? p.t : 0) : null }),
                 "A detached clip stays put when the video is cut or reordered")}
        </Section>
        <Section title="Volume">
          {num("Level", vc.gain_db, (v) => set({ gain_db: v }), { min: -60, max: 12, step: 1, unit: "dB" })}
          {check("Mute", vc.muted, (v) => set({ muted: v }))}
        </Section>
        <Section title="Text">
          <div className="pp-actions">
            <button className="pp-btn" disabled={busy || c.status !== "ready"} title="Split at the middle word; both halves are re-voiced"
                    onClick={() => contentOp(async () => {
                      const mid = c.text.lastIndexOf(" ", Math.floor(c.text.length / 2)) + 1 || Math.floor(c.text.length / 2);
                      await editor.splitChunk(project.id, c.id, c.revision, mid);
                    })}>Split text</button>
            <button className="pp-btn" disabled={busy || !next || c.status !== "ready" || next.status !== "ready"}
                    title="Merge with the next chunk; re-voiced as one"
                    onClick={() => contentOp(async () => { await editor.mergeChunks(project.id, c, next); setSel(null); })}>Merge with next</button>
          </div>
        </Section>
      </>
    );
  }

  if (sel.kind === "music") {
    const m = doc.music.clips.find((x) => x.id === sel.id);
    if (!m) return null;
    const mlen = Number(media.find((x) => String(x.id) === m.media_id)?.duration_s || m.media_out);
    const set = (fields) => tl.run([{ type: "music.set", clip_id: m.id, fields }]);
    return (
      <>
        <div className="pp-subject"><span className="pp-chip pp-chip-music">A3</span> {media.find((x) => String(x.id) === m.media_id)?.filename || "Music"}</div>
        <Section title="Timing">
          {num("Start on timeline", m.t, (v) => set({ t: v }), { min: 0, unit: "s" })}
          {num("In point", m.media_in, (v) => set({ media_in: v }), { min: 0, max: mlen, unit: "s" })}
          {num("Out point", m.media_out, (v) => set({ media_out: v }), { min: 0, max: mlen, unit: "s" })}
        </Section>
        <Section title="Volume">
          {num("Level", m.gain_db, (v) => set({ gain_db: v }), { min: -60, max: 12, step: 1, unit: "dB" })}
          {num("Fade in", m.fade_in, (v) => set({ fade_in: v }), { min: 0, max: 30, unit: "s" })}
          {num("Fade out", m.fade_out, (v) => set({ fade_out: v }), { min: 0, max: 30, unit: "s" })}
        </Section>
        <div className="pp-actions">
          <button className="pp-btn pp-btn-danger" onClick={() => { tl.run([{ type: "music.delete", clip_id: m.id }]); setSel(null); }}>Remove clip</button>
        </div>
      </>
    );
  }

  if (sel.kind === "video") {
    const c = doc.video.find((x) => x.id === sel.id);
    if (!c) return null;
    const i = doc.video.findIndex((x) => x.id === c.id);
    const nx = doc.video[i + 1], pv = doc.video[i - 1];
    return (
      <>
        <div className="pp-subject"><span className="pp-chip pp-chip-video">V1</span> Video clip {i + 1} of {doc.video.length}</div>
        <Section title="Source">
          <div className="pp-kv"><span>In</span><span className="mono">{timecode(c.src_in)}</span></div>
          <div className="pp-kv"><span>Out</span><span className="mono">{timecode(c.src_out)}</span></div>
          <div className="pp-kv"><span>Duration</span><span className="mono">{timecode(c.src_out - c.src_in)}</span></div>
          <p className="pp-note">Voice anchored inside this clip moves with it, and disappears if the clip is deleted.</p>
        </Section>
        <div className="pp-actions">
          {pv && Math.abs(pv.src_out - c.src_in) < 1e-3 && (
            <button className="pp-btn" onClick={() => tl.run([{ type: "video.join", clip_id: pv.id, next_id: c.id }])}>Join with previous</button>
          )}
          {nx && Math.abs(c.src_out - nx.src_in) < 1e-3 && (
            <button className="pp-btn" onClick={() => tl.run([{ type: "video.join", clip_id: c.id, next_id: nx.id }])}>Join with next</button>
          )}
          {doc.video.length > 1 && (
            <button className="pp-btn pp-btn-danger" onClick={() => { tl.run([{ type: "video.delete", clip_id: c.id }]); setSel(null); }}>Delete clip</button>
          )}
        </div>
      </>
    );
  }
  return null;
}

function audioDuration(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const a = new Audio();
    a.preload = "metadata";
    a.onloadedmetadata = () => { URL.revokeObjectURL(url); a.duration > 0 && Number.isFinite(a.duration) ? resolve(a.duration) : reject(new Error("couldn't read the audio length")); };
    a.onerror = () => { URL.revokeObjectURL(url); reject(new Error("that file isn't playable audio")); };
    a.src = url;
  });
}
