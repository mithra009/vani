// Multi-track timeline editor (R6, R7, D2–D6, D9, D11): video / original audio / voice / music /
// captions, instant local edits with undo/redo + autosave, and a live Web Audio preview.
import { useEffect, useMemo, useRef, useState } from "react";
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

export default function TimelineEditor({ project, chunks }) {
  const [media, setMedia] = useState([]);
  const ctx = useMemo(() => ({
    sourceS: Number(project.duration_s || 0),
    chunkIds: new Set(chunks.map((c) => String(c.id))),
    media: Object.fromEntries(media.map((m) => [String(m.id), Number(m.duration_s)])),
  }), [project.duration_s, chunks, media]);
  const tl = useTimeline(project.id, ctx);

  const [zoom, setZoom] = useState(40);                  // px per second
  const [sel, setSel] = useState(null);                  // {kind: video|voice|music, id}
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [err, setErr] = useState(null);
  const [proxyUrl, setProxyUrl] = useState(null);
  const videoRef = useRef(null);
  const engine = useRef(null);

  // Music list + proxy URL.
  useEffect(() => {
    editor.getTimeline(project.id).then((r) => setMedia(r.media || [])).catch((e) => setErr(e.message));
    api.assetPreviewUrl(project.asset_id)
      .then((r) => setProxyUrl(r.url))
      .catch((e) => setErr(`Preview video unavailable: ${e.message}`));
  }, [project.id, project.asset_id]);

  // Preview engine lifetime.
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

  // Keyboard: space play, ctrl+z / ctrl+shift+z.
  useEffect(() => {
    const onKey = (e) => {
      if (tl.status !== "ready" || /input|textarea|select/i.test(e.target.tagName)) return;
      if (e.key === " ") { e.preventDefault(); togglePlay(); }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? tl.redo() : tl.undo(); }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") { e.preventDefault(); tl.redo(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const [loadingPlay, setLoadingPlay] = useState(false);

  // A just-uploaded music file is placed once it is part of the validation context.
  const [pendingMusic, setPendingMusic] = useState(null);
  useEffect(() => {
    if (pendingMusic && ctx.media[pendingMusic.id] && tl.status === "ready") {
      tl.run([{ type: "music.add", clip: { media_id: pendingMusic.id, t: pendingMusic.t } }]);
      setPendingMusic(null);
    }
  }, [pendingMusic, ctx, tl]);

  if (tl.status === "loading") return <div className="spinner" style={{ margin: "40px auto" }} />;
  if (tl.status === "error") return <div className="banner error" role="alert"><span className="banner-dot" />Timeline failed to load: {tl.error}</div>;

  const doc = tl.doc;
  const end = durationT(doc);
  const vl = videoLayout(doc);
  const { placed, hidden } = layout(doc, chunks);
  const byId = Object.fromEntries(chunks.map((c) => [String(c.id), c]));
  const width = Math.max(600, end * zoom + 80);
  const caption = doc.captions.enabled ? placed.find((p) => !p.muted && t >= p.t && t < p.t + p.length) : null;

  async function togglePlay() {
    if (!engine.current || loadingPlay) return;
    if (playing) { engine.current.stop(); return; }
    setErr(null);
    setLoadingPlay(true);
    try { await engine.current.play(doc, chunks, t); }
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

  function splitVideoAtPlayhead() {
    const c = vl.find((v) => t > v.t + 0.05 && t < v.t + (v.src_out - v.src_in) - 0.05);
    if (!c) { setErr("Put the playhead inside a video clip to split it."); return; }
    tl.run([{ type: "video.split", clip_id: c.id, at_src: round3(c.src_in + (t - c.t)) }]);
  }

  return (
    <div className="tl">
      <div className="tl-stage">
        <div className="tl-video-wrap">
          {proxyUrl
            ? <video ref={videoRef} src={proxyUrl} crossOrigin="anonymous" playsInline preload="auto" className="tl-video"
                     onError={() => setErr("The preview video failed to load (the link may have expired; reload the page).")} />
            : <div className="tl-video tl-video-empty">Preview video is still processing…</div>}
          {caption && <div className="tl-caption">{byId[caption.chunk_id]?.text}</div>}
        </div>
        <Inspector sel={sel} setSel={setSel} doc={doc} tl={tl} placed={placed} byId={byId} chunks={chunks}
                   project={project} media={media} setErr={setErr} />
      </div>

      <div className="tl-toolbar">
        <button className="btn btn-primary btn-sm tl-play" onClick={togglePlay} disabled={!proxyUrl || loadingPlay}
                aria-label={playing ? "Pause" : "Play"} title="Space">
          {loadingPlay ? "Loading…" : playing ? "❚❚ Pause" : "▶ Play"}
        </button>
        <span className="mono tl-time">{clock(t)} / {clock(end)}</span>
        <button className="btn btn-sm" onClick={tl.undo} disabled={!tl.canUndo} title="Ctrl+Z">↶ Undo</button>
        <button className="btn btn-sm" onClick={tl.redo} disabled={!tl.canRedo} title="Ctrl+Shift+Z">↷ Redo</button>
        <SaveState save={tl.save} />
        <button className="btn btn-sm" onClick={splitVideoAtPlayhead}>✂ Split video</button>
        <label className="tl-check"><input type="checkbox" checked={doc.captions.enabled}
          onChange={(e) => tl.run([{ type: "track.set", track: "captions", fields: { enabled: e.target.checked } }])} /> Captions</label>
        <MusicUpload project={project} onAdded={(m) => {
          setMedia((ms) => [...ms, m]);
          setPendingMusic({ id: String(m.id), t: round3(t) });
        }} setErr={setErr} />
        <span style={{ flex: 1 }} />
        <label className="body-sm">Zoom <input type="range" min={10} max={160} value={zoom} onChange={(e) => setZoom(+e.target.value)} /></label>
      </div>

      {err && <div className="banner error" role="alert"><span className="banner-dot" /><span>{err}</span>
        <button className="link-btn" onClick={() => setErr(null)}>Dismiss</button></div>}
      {tl.notices.map((n) => (
        <div key={n.id} className="banner warn" role="status"><span className="banner-dot" /><span>{n.msg}</span>
          <button className="link-btn" onClick={() => tl.dismiss(n.id)}>Dismiss</button></div>
      ))}

      <div className="tl-scroll">
        <div className="tl-tracks" style={{ width }}>
          <Ruler end={end} zoom={zoom} onSeek={seek} playing={playing} />
          <Playhead t={t} zoom={zoom} onSeek={seek} playing={playing} />

          <TrackRow label="Video">
            {vl.map((c, i) => (
              <VideoClip key={c.id} c={c} i={i} n={vl.length} next={vl[i + 1]} zoom={zoom} selected={sel?.id === c.id}
                         onSelect={() => setSel({ kind: "video", id: c.id })} tl={tl} sourceS={ctx.sourceS} />
            ))}
          </TrackRow>

          <TrackRow label="Original" muted={doc.original_audio.muted}>
            <div className="tl-clip tl-clip-orig" style={{ left: 0, width: end * zoom }}
                 onClick={() => setSel({ kind: "original" })}>
              {doc.original_audio.muted ? "muted" : `${doc.original_audio.gain_db} dB${doc.original_audio.auto_duck ? " · ducks under voice" : ""}`}
            </div>
          </TrackRow>

          <TrackRow label="Voice">
            {placed.map((p) => (
              <DragClip key={p.chunk_id} left={p.t * zoom} width={Math.max(4, p.length * zoom)} zoom={zoom}
                        className={`tl-clip tl-clip-voice ${p.flags.length ? "flagged" : ""} ${p.muted ? "muted" : ""} ${sel?.id === p.chunk_id ? "sel" : ""}`}
                        title={[byId[p.chunk_id]?.text, ...p.flags.map((f) => `⚠ ${FLAG_TEXT[f]}`)].join("\n")}
                        onSelect={() => setSel({ kind: "voice", id: p.chunk_id })}
                        onDrop={(dt) => {
                          const vc = doc.voice.clips[p.chunk_id] || {};
                          const fields = vc.detached_t != null
                            ? { detached_t: round3(Math.max(0, vc.detached_t + dt)) }
                            : { offset: round3((vc.offset || 0) + dt) };
                          tl.run([{ type: "voice.set", chunk_id: p.chunk_id, fields }]);
                        }}>
                {p.flags.length > 0 && <span className="tl-flag">⚠</span>}
                <span className="tl-clip-text">{byId[p.chunk_id]?.text}</span>
              </DragClip>
            ))}
          </TrackRow>

          <TrackRow label="Music">
            {doc.music.clips.map((m) => (
              <DragClip key={m.id} left={m.t * zoom} width={Math.max(4, (m.media_out - m.media_in) * zoom)} zoom={zoom}
                        className={`tl-clip tl-clip-music ${sel?.id === m.id ? "sel" : ""}`}
                        onSelect={() => setSel({ kind: "music", id: m.id })}
                        onDrop={(dt) => tl.run([{ type: "music.set", clip_id: m.id, fields: { t: round3(Math.max(0, m.t + dt)) } }])}>
                <span className="tl-clip-text">{media.find((x) => String(x.id) === m.media_id)?.filename || "audio"}</span>
              </DragClip>
            ))}
          </TrackRow>
        </div>
      </div>

      {hidden.length > 0 && (
        <p className="caption dim" style={{ marginTop: 8 }}>
          Not on the timeline: {hidden.map((h) => `#${(byId[h.chunk_id]?.idx ?? 0) + 1} (${HIDDEN_TEXT[h.reason]})`).join(", ")}
        </p>
      )}
    </div>
  );
}

const round3 = (x) => Math.round(x * 1000) / 1000;

function SaveState({ save }) {
  const label = { saved: "✓ All changes saved", saving: "Syncing…", retrying: "Not saved, retrying…", error: "Not saved" }[save.state];
  return (
    <span className={`tl-save tl-save-${save.state}`} role="status" aria-live="polite" title={save.message || ""}>
      {save.state === "saving" && <span className="tl-save-dot" />}{label}
    </span>
  );
}

/** Seek by dragging: pointer x inside the tracks area to seconds. Resumes playback on release if it was playing. */
function useScrub(zoom, onSeek, playing) {
  const wasPlaying = useRef(false);
  const at = (e) => (e.clientX - e.currentTarget.closest(".tl-tracks").getBoundingClientRect().left - 80) / zoom;
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
    <div className="tl-playhead" style={{ left: t * zoom }}>
      <span className="tl-playhead-grip" {...scrub} title="Drag to move the playhead" />
    </div>
  );
}

function TrackRow({ label, muted, children }) {
  return (
    <div className={`tl-row ${muted ? "muted" : ""}`}>
      <span className="tl-row-label">{label}</span>
      <div className="tl-row-lane">{children}</div>
    </div>
  );
}

function Ruler({ end, zoom, onSeek, playing }) {
  const scrub = useScrub(zoom, onSeek, playing);
  const step = zoom >= 80 ? 1 : zoom >= 30 ? 5 : 10;
  const ticks = [];
  for (let s = 0; s <= end; s += step) ticks.push(s);
  return (
    <div className="tl-ruler" {...scrub}>
      {ticks.map((s) => <span key={s} className="tl-tick" style={{ left: s * zoom }}>{clock(s)}</span>)}
    </div>
  );
}

/** A clip you can click to select and drag horizontally; commits one op on release. */
function DragClip({ left, width, zoom, className, title, onSelect, onDrop, children }) {
  const [dx, setDx] = useState(0);
  const start = useRef(null);
  return (
    <div className={className} title={title} style={{ left: left + dx, width }}
         onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); start.current = e.clientX; onSelect(); }}
         onPointerMove={(e) => { if (start.current != null) setDx(e.clientX - start.current); }}
         onPointerUp={() => {
           const moved = dx;
           start.current = null; setDx(0);
           if (Math.abs(moved) > 2) onDrop(moved / zoom);
         }}>
      {children}
    </div>
  );
}

function VideoClip({ c, i, n, next, zoom, selected, onSelect, tl, sourceS }) {
  // Joinable: the next clip continues exactly where this one ends in the source (an undone cut).
  const joinable = next && Math.abs(next.src_in - c.src_out) < 1e-3;
  const len = c.src_out - c.src_in;
  const [trim, setTrim] = useState(null);     // {side, dx}
  const startX = useRef(0);
  const handle = (side) => ({
    onPointerDown: (e) => { e.stopPropagation(); e.currentTarget.setPointerCapture(e.pointerId); startX.current = e.clientX; setTrim({ side, dx: 0 }); },
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
  return (
    <div className={`tl-clip tl-clip-video ${selected ? "sel" : ""}`} style={{ left: c.t * zoom + dl, width: Math.max(6, len * zoom + dw) }}
         onPointerDown={onSelect}>
      <span className="tl-handle in" {...handle("in")} />
      <span className="tl-clip-text">{clock(c.src_in)}–{clock(c.src_out)}</span>
      <span className="tl-clip-actions">
        {i > 0 && <button onClick={(e) => { e.stopPropagation(); tl.run([{ type: "video.move", clip_id: c.id, index: i - 1 }]); }} title="Move earlier">◀</button>}
        {i < n - 1 && <button onClick={(e) => { e.stopPropagation(); tl.run([{ type: "video.move", clip_id: c.id, index: i + 1 }]); }} title="Move later">▶</button>}
        {joinable && <button onClick={(e) => { e.stopPropagation(); tl.run([{ type: "video.join", clip_id: c.id, next_id: next.id }]); }} title="Join with the next clip">⊕</button>}
        {n > 1 && <button onClick={(e) => { e.stopPropagation(); tl.run([{ type: "video.delete", clip_id: c.id }]); }} title="Delete (voice in it disappears)">✕</button>}
      </span>
      <span className="tl-handle out" {...handle("out")} />
    </div>
  );
}

function Inspector({ sel, setSel, doc, tl, placed, byId, chunks, project, media, setErr }) {
  const [busy, setBusy] = useState(false);
  if (!sel) {
    return <aside className="tl-inspector dim body-sm">Select a clip to adjust it. Drag voice and music clips to move them; drag the edges of video clips to trim.</aside>;
  }
  const num = (label, value, onCommit, { min, max, step = 0.05 } = {}) => (
    <label className="tl-field">{label}
      <input type="number" className="input" defaultValue={value} key={`${label}${value}`} min={min} max={max} step={step}
             onBlur={(e) => { const v = parseFloat(e.target.value); if (Number.isFinite(v) && v !== value) onCommit(v); }} />
    </label>
  );

  if (sel.kind === "original") {
    const oa = doc.original_audio;
    const set = (fields) => tl.run([{ type: "track.set", track: "original_audio", fields }]);
    return (
      <aside className="tl-inspector">
        <h3 className="tl-insp-title">Original audio</h3>
        {num("Gain (dB)", oa.gain_db, (v) => set({ gain_db: v }), { min: -60, max: 12, step: 1 })}
        <label className="tl-check"><input type="checkbox" checked={oa.muted} onChange={(e) => set({ muted: e.target.checked })} /> Mute</label>
        <label className="tl-check"><input type="checkbox" checked={oa.auto_duck} onChange={(e) => set({ auto_duck: e.target.checked })} /> Duck under the voice</label>
      </aside>
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
      <aside className="tl-inspector">
        <h3 className="tl-insp-title">Voice #{c.idx + 1}</h3>
        <p className="body-sm">{c.text}</p>
        {p?.flags.map((f) => <p key={f} className="caption tl-warn">⚠ {FLAG_TEXT[f]}</p>)}
        {vc.detached_t == null
          ? num("Offset (s)", vc.offset, (v) => set({ offset: v }), { min: -30, max: 30 })
          : num("Position (s)", vc.detached_t, (v) => set({ detached_t: v }), { min: 0 })}
        {num("Cut from start (s)", vc.trim_in, (v) => set({ trim_in: v }), { min: 0 })}
        {num("Cut from end (s)", vc.trim_out, (v) => set({ trim_out: v }), { min: 0 })}
        <p className="caption dim">
          Plays {(Math.max(0, Number(c.audio_duration_s || 0) - vc.trim_in - vc.trim_out)).toFixed(2)} s
          of {Number(c.audio_duration_s || 0).toFixed(2)} s. 0 means nothing is cut.
        </p>
        {num("Gain (dB)", vc.gain_db, (v) => set({ gain_db: v }), { min: -60, max: 12, step: 1 })}
        <label className="tl-check"><input type="checkbox" checked={vc.muted} onChange={(e) => set({ muted: e.target.checked })} /> Mute</label>
        <label className="tl-check" title="A detached clip stays put when the video is cut or reordered">
          <input type="checkbox" checked={vc.detached_t != null}
                 onChange={(e) => set({ detached_t: e.target.checked ? round3(p ? p.t : 0) : null })} /> Detach from video</label>
        <div className="tl-insp-actions">
          <button className="btn btn-sm" disabled={busy || c.status !== "ready"} title="Splits the text at the middle space and regenerates both halves"
                  onClick={() => contentOp(async () => {
                    const mid = c.text.lastIndexOf(" ", Math.floor(c.text.length / 2)) + 1 || Math.floor(c.text.length / 2);
                    await editor.splitChunk(project.id, c.id, c.revision, mid);
                  })}>Split text</button>
          <button className="btn btn-sm" disabled={busy || !next || c.status !== "ready" || next.status !== "ready"}
                  title="Merge with the next chunk and regenerate"
                  onClick={() => contentOp(async () => { await editor.mergeChunks(project.id, c, next); setSel(null); })}>Merge with next</button>
        </div>
      </aside>
    );
  }

  if (sel.kind === "music") {
    const m = doc.music.clips.find((x) => x.id === sel.id);
    if (!m) return null;
    const mlen = Number(media.find((x) => String(x.id) === m.media_id)?.duration_s || m.media_out);
    const set = (fields) => tl.run([{ type: "music.set", clip_id: m.id, fields }]);
    return (
      <aside className="tl-inspector">
        <h3 className="tl-insp-title">Music</h3>
        {num("Start on timeline (s)", m.t, (v) => set({ t: v }), { min: 0 })}
        {num("From (s)", m.media_in, (v) => set({ media_in: v }), { min: 0, max: mlen })}
        {num("To (s)", m.media_out, (v) => set({ media_out: v }), { min: 0, max: mlen })}
        {num("Fade in (s)", m.fade_in, (v) => set({ fade_in: v }), { min: 0, max: 30 })}
        {num("Fade out (s)", m.fade_out, (v) => set({ fade_out: v }), { min: 0, max: 30 })}
        {num("Gain (dB)", m.gain_db, (v) => set({ gain_db: v }), { min: -60, max: 12, step: 1 })}
        <button className="btn btn-sm" onClick={() => { tl.run([{ type: "music.delete", clip_id: m.id }]); setSel(null); }}>Remove</button>
      </aside>
    );
  }

  if (sel.kind === "video") {
    const c = doc.video.find((x) => x.id === sel.id);
    if (!c) return null;
    return (
      <aside className="tl-inspector">
        <h3 className="tl-insp-title">Video clip</h3>
        <p className="body-sm">Source {clock(c.src_in)} – {clock(c.src_out)}</p>
        <p className="caption dim">Voice anchored inside this clip moves with it, and disappears if the clip is deleted.</p>
        <div className="tl-insp-actions">
          {(() => {
            const i = doc.video.findIndex((x) => x.id === c.id);
            const nx = doc.video[i + 1], pv = doc.video[i - 1];
            return (
              <>
                {pv && Math.abs(pv.src_out - c.src_in) < 1e-3 && (
                  <button className="btn btn-quiet btn-xs" onClick={() => tl.run([{ type: "video.join", clip_id: pv.id, next_id: c.id }])}>Join with previous</button>
                )}
                {nx && Math.abs(c.src_out - nx.src_in) < 1e-3 && (
                  <button className="btn btn-quiet btn-xs" onClick={() => tl.run([{ type: "video.join", clip_id: c.id, next_id: nx.id }])}>Join with next</button>
                )}
                {doc.video.length > 1 && (
                  <button className="btn btn-quiet btn-xs" onClick={() => { tl.run([{ type: "video.delete", clip_id: c.id }]); setSel(null); }}>Delete clip</button>
                )}
              </>
            );
          })()}
        </div>
        {doc.video.length > 1 && !doc.video.some((x, j) => j > 0 && Math.abs(doc.video[j - 1].src_out - x.src_in) < 1e-3) && (
          <p className="caption dim">Clips can be joined only when they're next to each other and continue the same footage.</p>
        )}
      </aside>
    );
  }
  return null;
}

function MusicUpload({ project, onAdded, setErr }) {
  const input = useRef(null);
  const [busy, setBusy] = useState(null);
  async function pick(f) {
    if (!f) return;
    setErr(null);
    try {
      setBusy("Reading…");
      const duration = await audioDuration(f);
      setBusy("Uploading…");
      const init = await editor.mediaInit(project.id, f.name, duration);
      await uploadToStorage(f, init.uploadUrl, (p) => setBusy(`Uploading ${Math.round(p * 100)}%`));
      const m = await editor.mediaComplete(project.id, init.media.id);
      onAdded(m);
    } catch (e) {
      setErr(`Music upload failed: ${e.message}`);
    } finally {
      setBusy(null);
      if (input.current) input.current.value = "";
    }
  }
  return (
    <>
      <input ref={input} type="file" accept=".mp3,.wav,.m4a,.aac,.ogg,.flac,audio/*" hidden onChange={(e) => pick(e.target.files[0])} />
      <button className="btn btn-sm" onClick={() => input.current?.click()} disabled={!!busy}>{busy || "♫ Add music"}</button>
    </>
  );
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
