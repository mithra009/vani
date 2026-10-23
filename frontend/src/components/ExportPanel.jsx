// Export (R8, D10): format × resolution, audio-only mix choice (C13), captions (C3), progress,
// downloads. Polls while anything is rendering; every failure is shown with its reason.
import { useEffect, useState } from "react";
import { Loader } from "./Icons.jsx";
import * as editor from "../lib/editorApi.js";
import { ago } from "../lib/format.js";

const FORMATS = [
  { id: "mp4", label: "MP4", note: "H.264 video, AAC audio. Plays everywhere." },
  { id: "webm", label: "WebM", note: "VP9 video, Opus audio. Smaller files for the web." },
  { id: "mov", label: "MOV", note: "H.264 video, AAC audio, in a QuickTime container." },
  { id: "mp3", label: "MP3", note: "Audio only." },
  { id: "wav", label: "WAV", note: "Audio only, uncompressed." },
];
const CAPTIONS = [
  { id: "none", label: "None", summary: "no captions", hint: "No captions." },
  { id: "srt", label: "SRT", summary: "SRT captions", hint: "A separate .srt caption file, downloaded alongside." },
  { id: "vtt", label: "VTT", summary: "VTT captions", hint: "A separate .vtt caption file, downloaded alongside." },
  { id: "burn", label: "Burned in", summary: "burned-in captions", hint: "Captions drawn into the video picture." },
];
const HEIGHTS = [480, 720, 1080];
const POLL_MS = 2000;

const WARNING_TEXT = {
  overlap: "overlaps another voice clip (both play, mixed)",
  past_end: "runs past the end of the video and is cut off",
  before_start: "starts before 0:00 and its start is cut off",
  on_cut: "speech runs into a cut in the video",
  video_cut: "isn't in the export: its part of the video was cut",
  no_audio: "isn't in the export: it has no audio",
  unplaced: "isn't in the export: it isn't placed on the timeline",
};

export default function ExportPanel({ project, chunks = [] }) {
  const [openWarn, setOpenWarn] = useState(null);     // export id whose warnings are expanded
  const chunkNo = Object.fromEntries(chunks.map((c) => [String(c.id), c.idx + 1]));
  const [format, setFormat] = useState("mp4");
  const [height, setHeight] = useState(720);
  const [audioMix, setAudioMix] = useState("full");
  const [captions, setCaptions] = useState("none");
  const [list, setList] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const audioOnly = format === "mp3" || format === "wav";

  const refresh = () => editor.listExports(project.id).then(setList).catch((e) => setErr(`Couldn't load exports: ${e.message}`));
  useEffect(() => { refresh(); }, [project.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const active = list.some((e) => e.status === "queued" || e.status === "rendering");
  useEffect(() => {
    if (!active) return;
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (audioOnly && captions === "burn") setCaptions("none"); }, [audioOnly, captions]);

  async function start() {
    setBusy(true); setErr(null);
    try {
      await editor.createExport(project.id, {
        format, height: audioOnly ? null : height, audio_mix: audioOnly ? audioMix : "full", captions,
      });
      await refresh();
    } catch (e) { setErr(e.message); }
    setBusy(false);
  }

  async function download(e, which) {
    try {
      const r = await editor.exportUrl(project.id, e.id);
      const url = which === "captions" ? r.captions_url : r.url;
      if (!url) throw new Error("No file to download.");
      window.open(url, "_blank", "noopener");
    } catch (x) { setErr(`Download failed: ${x.message}`); }
  }

  const notReady = project.status !== "editing";
  const fmt = FORMATS.find((f) => f.id === format);
  const capOpts = audioOnly ? CAPTIONS.filter((c) => c.id !== "burn") : CAPTIONS;
  const summary = [
    `${fmt.label}`,
    audioOnly ? (audioMix === "full" ? "full mix" : "voice only") : `${height}p`,
    CAPTIONS.find((c) => c.id === captions).summary,
  ].join(" · ");

  return (
    <div className="xp">
      <section className="xp-card" aria-labelledby="xp-settings">
        <header className="xp-card-head">
          <h2 id="xp-settings" className="xp-card-title">Export settings</h2>
        </header>

        <div className="xp-rows">
          <Row label="Format" hint={fmt.note}>
            <Segmented value={format} onChange={setFormat} options={FORMATS.map((f) => ({ id: f.id, label: f.label }))} label="Format" />
          </Row>
          {!audioOnly ? (
            <Row label="Resolution" hint="Never upscaled past the source video.">
              <Segmented value={height} onChange={setHeight} options={HEIGHTS.map((h) => ({ id: h, label: `${h}p` }))} label="Resolution" />
            </Row>
          ) : (
            <Row label="Audio" hint={audioMix === "full" ? "Voice, original audio and music, mixed." : "Only the generated voice."}>
              <Segmented value={audioMix} onChange={setAudioMix} label="Audio"
                         options={[{ id: "full", label: "Full mix" }, { id: "voice", label: "Voice only" }]} />
            </Row>
          )}
          <Row label="Captions" hint={CAPTIONS.find((c) => c.id === captions).hint}>
            <Segmented value={captions} onChange={setCaptions} options={capOpts} label="Captions" />
          </Row>
        </div>

        {err && <div className="banner error xp-err" role="alert"><span className="banner-dot" /><span>{err}</span></div>}

        <footer className="xp-card-foot">
          <div className="xp-summary">
            <span className="xp-summary-label">Output</span>
            <span className="xp-summary-value">{summary}</span>
            {notReady && <span className="xp-summary-note">Unlocks when every chunk has its audio.</span>}
          </div>
          <button className="btn btn-primary btn-ctl" onClick={start} disabled={busy || notReady}>
            {busy ? "Starting…" : "Export"}
          </button>
        </footer>
      </section>

      <section className="xp-card" aria-labelledby="xp-list">
        <header className="xp-card-head">
          <h2 id="xp-list" className="xp-card-title">Exports</h2>
          {list.length > 0 && <span className="xp-count">{list.length}</span>}
        </header>
        {list.length === 0 ? (
          <div className="xp-empty">
            <p>No exports yet.</p>
            <p className="dim">Choose the settings and press Export. Finished files appear here to download.</p>
          </div>
        ) : (
          <ul className="xp-list">
            {list.map((e, i) => {
              const cap = CAPTIONS.find((c) => c.id === e.captions);
              const working = e.status === "queued" || e.status === "rendering";
              return (
                <li key={e.id} className={`xp-item xp-${e.status}`}>
                  <div className="xp-item-main">
                    {/* The list is newest first, so the oldest export is #1. */}
                    <span className="xp-n">#{list.length - i}</span>
                    <div className="xp-item-id">
                      <span className="xp-item-title">{e.format.toUpperCase()} · {e.height ? `${e.height}p` : e.audio_mix === "voice" ? "voice only" : "full mix"}</span>
                      <span className="xp-item-meta">{ago(Date.parse(e.created_at))}{cap && e.captions !== "none" ? ` · ${cap.summary}` : ""}</span>
                    </div>
                    <div className="xp-item-side">
                      {working && (
                        <span className="xp-progress" title={`${Math.round(e.progress * 100)}%`}>
                          <Loader size={16} />
                          <span className="xp-progress-bar"><span style={{ width: `${Math.max(3, Math.round(e.progress * 100))}%` }} /></span>
                          <span className="xp-progress-n mono">{e.status === "queued" ? "Queued" : `${Math.round(e.progress * 100)}%`}</span>
                        </span>
                      )}
                      {e.status === "ready" && (
                        <>
                          {e.has_captions && <button className="btn btn-quiet btn-xs" onClick={() => download(e, "captions")}>Captions</button>}
                          <button className="btn btn-primary btn-xs" onClick={() => download(e, "video")}>Download</button>
                        </>
                      )}
                      {e.status === "failed" && <span className="xp-pill xp-pill-failed">Failed</span>}
                    </div>
                  </div>
                  {e.status === "failed" && <p className="xp-item-error">{e.error_message}</p>}
                  {e.warnings?.length > 0 && (
                    <button className="export-warn-btn xp-warn" aria-expanded={openWarn === e.id}
                            onClick={() => setOpenWarn((x) => (x === e.id ? null : e.id))}>
                      ⚠ {e.warnings.length} warning{e.warnings.length > 1 ? "s" : ""}
                      <span className="export-warn-caret" aria-hidden="true">{openWarn === e.id ? "▴" : "▾"}</span>
                    </button>
                  )}
                  {openWarn === e.id && (
                    <ul className="export-warn-list">
                      {e.warnings.flatMap((w) => w.flags.map((f) => (
                        <li key={`${w.chunk_id}-${f}`}>
                          <b>{chunkNo[w.chunk_id] ? `Chunk ${chunkNo[w.chunk_id]}` : "A removed chunk"}</b> {WARNING_TEXT[f] || f}.
                        </li>
                      )))}
                      <li className="export-warn-hint">Fix these on the Timeline tab, then export again. Warnings don't stop an export.</li>
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}

function Row({ label, hint, children }) {
  return (
    <div className="xp-row">
      <span className="xp-row-label">{label}</span>
      <div className="xp-row-control">
        {children}
        {hint && <span className="xp-row-hint">{hint}</span>}
      </div>
    </div>
  );
}

/** One control, equal segments: the standard pattern for a single choice among a few options. */
function Segmented({ value, onChange, options, label }) {
  return (
    <div className="xp-seg" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.id} role="radio" aria-checked={value === o.id} className={value === o.id ? "on" : ""}
                onClick={() => onChange(o.id)}>{o.label}</button>
      ))}
    </div>
  );
}
