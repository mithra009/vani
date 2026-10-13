// Export (R8, D10): format × resolution, audio-only mix choice (C13), captions (C3), progress,
// downloads. Polls while anything is rendering; every failure is shown with its reason.
import { useEffect, useState } from "react";
import * as editor from "../lib/editorApi.js";
import { ago } from "../lib/format.js";

const FORMATS = [
  { id: "mp4", label: "MP4", note: "H.264 + AAC" },
  { id: "webm", label: "WebM", note: "VP9 + Opus" },
  { id: "mov", label: "MOV", note: "H.264 + AAC" },
  { id: "mp3", label: "MP3", note: "audio only" },
  { id: "wav", label: "WAV", note: "audio only" },
];
const HEIGHTS = [480, 720, 1080];
const POLL_MS = 2000;

export default function ExportPanel({ project }) {
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
  return (
    <div className="export-panel">
      <div className="export-form">
        <div className="export-group">
          <span className="field-label">Format</span>
          <div className="chip-row">
            {FORMATS.map((f) => (
              <button key={f.id} className={`chip-btn ${format === f.id ? "on" : ""}`} onClick={() => setFormat(f.id)}>
                {f.label} <small>{f.note}</small>
              </button>
            ))}
          </div>
        </div>
        {!audioOnly ? (
          <div className="export-group">
            <span className="field-label">Resolution</span>
            <div className="chip-row">
              {HEIGHTS.map((h) => (
                <button key={h} className={`chip-btn ${height === h ? "on" : ""}`} onClick={() => setHeight(h)}>{h}p</button>
              ))}
            </div>
            <span className="caption dim">Never upscaled past the source video.</span>
          </div>
        ) : (
          <div className="export-group">
            <span className="field-label">Audio</span>
            <div className="chip-row">
              <button className={`chip-btn ${audioMix === "full" ? "on" : ""}`} onClick={() => setAudioMix("full")}>Full mix</button>
              <button className={`chip-btn ${audioMix === "voice" ? "on" : ""}`} onClick={() => setAudioMix("voice")}>Voice only</button>
            </div>
          </div>
        )}
        <div className="export-group">
          <span className="field-label">Captions</span>
          <div className="chip-row">
            {["none", "srt", "vtt", ...(audioOnly ? [] : ["burn"])].map((c) => (
              <button key={c} className={`chip-btn ${captions === c ? "on" : ""}`} onClick={() => setCaptions(c)}>
                {{ none: "None", srt: "SRT file", vtt: "VTT file", burn: "Burned in" }[c]}
              </button>
            ))}
          </div>
        </div>
        <button className="btn btn-primary" onClick={start} disabled={busy || notReady}>
          {busy ? "Starting…" : "Export"}
        </button>
        {notReady && <p className="caption dim">Export unlocks when every chunk has its audio.</p>}
        {err && <div className="banner error" role="alert"><span className="banner-dot" /><span>{err}</span></div>}
      </div>

      <div className="export-list">
        {list.length === 0 && <p className="dim body-sm">No exports yet.</p>}
        {list.map((e) => (
          <div key={e.id} className={`export-row export-${e.status}`}>
            <span className="mono">{e.format.toUpperCase()}{e.height ? ` ${e.height}p` : ""}</span>
            <span className="body-sm dim">v{e.timeline_version} · {ago(Date.parse(e.created_at))}</span>
            {(e.status === "queued" || e.status === "rendering") && (
              <span className="export-progress"><span style={{ width: `${Math.round(e.progress * 100)}%` }} /></span>
            )}
            {e.status === "ready" && (
              <>
                <button className="link-btn" onClick={() => download(e, "video")}>Download</button>
                {e.has_captions && <button className="link-btn" onClick={() => download(e, "captions")}>Captions</button>}
              </>
            )}
            {e.status === "failed" && <span className="caption" style={{ color: "var(--red)" }}>{e.error_message}</span>}
            {e.warnings?.length > 0 && (
              <span className="caption tl-warn" title={e.warnings.map((w) => w.flags.join(", ")).join("\n")}>
                ⚠ {e.warnings.length} warning{e.warnings.length > 1 ? "s" : ""}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
