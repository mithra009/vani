import { useCallback, useEffect, useRef, useState } from "react";
import { Loader } from "../components/Icons.jsx";
import { Link, useParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import * as editor from "../lib/editorApi.js";
import { api } from "../lib/api.js";
import { TARGET_LANGS, VOICES, langName, voicesFor } from "../lib/catalog.js";
import { clock } from "../lib/format.js";
import TimelineEditor from "../components/TimelineEditor.jsx";
import ExportPanel from "../components/ExportPanel.jsx";
import NarrationTake from "../components/NarrationTake.jsx";
import AudioPlayer from "../components/AudioPlayer.jsx";

// ─────────────────────────────────── Editor page ──────────────────────────────
// Shows one editor project: header, chunk list, voice picker.
// Subscribes to SSE for live updates while generating.

const STATUS_LABEL = {
  draft: "Draft", awaiting_narration: "Waiting for narration", generating: "Generating…",
  editing: "Ready to edit", failed: "Failed",
};

const CHUNK_STATUS = {
  pending: { label: "Queued", cls: "chunk-pending" },
  generating: { label: "Generating…", cls: "chunk-generating" },
  ready: { label: "Ready", cls: "chunk-ready" },
  failed: { label: "Failed", cls: "chunk-failed" },
};

const EMOTION_TAGS = [
  "neutral", "laugh", "chuckle", "giggle", "sigh", "exhales", "sniffles",
  "whispers", "softly", "shouting", "high-pitched", "stammers", "rushed", "slow", "pauses",
];

export default function EditorProject() {
  const { id } = useParams();
  const [data, setData] = useState(null);           // { project, chunks }
  const [error, setError] = useState(null);
  const [sseOk, setSseOk] = useState(true);
  const [tab, setTab] = useState("chunks");
  // The Timeline tab is a fixed app screen: exactly the window's height, no page scroll, no footer.
  const fixed = tab === "timeline" && data?.project?.status !== "awaiting_narration";
  useEffect(() => {
    document.body.classList.toggle("app-fixed", fixed);
    return () => document.body.classList.remove("app-fixed");
  }, [fixed]);
  // Collapsed chrome (Timeline tab only): the site nav and project header fold into one slim row.
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem("vani.editor.collapsed") === "1"; } catch { return false; }
  });
  const compact = fixed && collapsed;
  useEffect(() => {
    try { localStorage.setItem("vani.editor.collapsed", collapsed ? "1" : "0"); } catch { /* optional */ }
  }, [collapsed]);
  useEffect(() => {
    document.body.classList.toggle("editor-compact", compact);
    return () => document.body.classList.remove("editor-compact");
  }, [compact]);

  // Fetch once, then let SSE drive updates.
  useEffect(() => {
    let cancelled = false;
    editor.getProject(id)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [id]);

  // SSE subscription — reconnects automatically. A drop is only reported if it lasts 4 s,
  // so routine reconnects don't flash a warning.
  useEffect(() => {
    let downTimer = null;
    const unsub = editor.subscribe(id, {
      onSnapshot(snap) { setData(snap); },
      onError(e) { setError(e.message || "Live update error."); },
      onConnection(ok) {
        clearTimeout(downTimer);
        if (ok) setSseOk(true);
        else downTimer = setTimeout(() => setSseOk(false), 4000);
      },
    });
    return () => { clearTimeout(downTimer); unsub(); };
  }, [id]);

  if (error && !data) {
    return (
      <section className="ed-sec empty">
        <h1 className="title">Project not found</h1>
        <p>{error}</p>
        <Link to="/projects">Back to projects</Link>
      </section>
    );
  }

  if (!data) {
    return <div className="progress-wrap"><Loader size={36} style={{ margin: "0 auto" }} /></div>;
  }

  const { project, chunks } = data;

  return (
    <div className={`ed-page ${fixed ? "ed-page-fixed" : ""}`}>
      <ProjectHeader project={project} compact={compact}
                     collapse={fixed ? { collapsed, toggle: () => setCollapsed((c) => !c) } : null}
                     tabs={project.status === "awaiting_narration" ? null : (
        <div className="editor-tabs ed-tabs" role="tablist" aria-label="Project views">
          {[["chunks", "Chunks"], ["timeline", "Timeline"], ["export", "Export"]].map(([k, label]) => (
            <button key={k} role="tab" aria-selected={tab === k} className={`editor-tab ${tab === k ? "on" : ""}`}
                    onClick={() => setTab(k)}>{label}</button>
          ))}
        </div>
      )} />
      {!sseOk && (
        <section className="ed-sec" style={{ paddingTop: 0, paddingBottom: 0 }}>
          <div className="banner warn" role="status"><span className="banner-dot" /><span>Live updates paused — reconnecting…</span></div>
        </section>
      )}
      {project.error_message && (
        <section className="ed-sec" style={{ paddingTop: 0, paddingBottom: 0 }}>
          <div className="banner error" role="alert">
            <span className="banner-dot" />
            <span>{project.error_message}</span>
            {project.status === "failed" && (
              <button className="link-btn" style={{ marginLeft: 12 }}
                      onClick={() => editor.retryProject(id).catch((e) => setError(e.message))}>Retry</button>
            )}
          </div>
        </section>
      )}
      {error && (
        <section className="ed-sec" style={{ paddingTop: 0, paddingBottom: 0 }}>
          <div className="banner error" role="alert"><span className="banner-dot" /><span>{error}</span></div>
        </section>
      )}
      <section className="ed-sec" style={{ paddingTop: 0 }}>
        {project.status === "awaiting_narration" ? (
          <NarrationTake project={project} />
        ) : (
          <>
            {tab === "chunks" && <><VoicePicker project={project} /><ChunkList project={project} chunks={chunks} /></>}
            {tab === "timeline" && <TimelineEditor project={project} chunks={chunks} />}
            {tab === "export" && <ExportPanel project={project} chunks={chunks} />}
          </>
        )}
      </section>
    </div>
  );
}

// ─────────────────────────────────── Header ───────────────────────────────────

function CollapseButton({ collapse }) {
  if (!collapse) return null;
  const label = collapse.collapsed ? "Show the header" : "Hide the header for more editing space";
  return (
    <button className="ed-collapse" onClick={collapse.toggle} aria-label={label} title={label} aria-pressed={collapse.collapsed}>
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {collapse.collapsed ? <path d="M6 9l6 6 6-6" /> : <path d="M6 15l6-6 6 6" />}
      </svg>
    </button>
  );
}

// "Ready to edit" is the normal state, so it isn't shown; only states that need attention are.
function StatusPill({ status }) {
  if (status === "editing") return null;
  return <span className={`status-pill status-${status}`}>{status === "generating" && <Loader size={12} />}{STATUS_LABEL[status] || status}</span>;
}

function ProjectHeader({ project, tabs, compact, collapse }) {
  const KIND = { video_audio: "Dub of the video's audio", script: "Script voice-over", narration: "Narration" };
  if (compact) {
    return (
      <header className="ed-head ed-head-compact">
        <Link to="/projects" className="ed-back ed-back-icon" aria-label="Back to projects" title="Projects">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>
        </Link>
        <span className="ed-compact-title" title={project.name}>{project.name}</span>
        <StatusPill status={project.status} />
        <span style={{ flex: 1 }} />
        {tabs}
        <CollapseButton collapse={collapse} />
      </header>
    );
  }
  return (
    <header className="ed-head">
      <Link to="/projects" className="ed-back">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>
        Projects
      </Link>
      <div className="ed-head-row">
        <div className="ed-head-main">
          <div className="ed-title-row">
            <h1 className="ed-title" title={project.name}>{project.name}</h1>
            <StatusPill status={project.status} />
          </div>
          <div className="ed-meta">
            <span>{KIND[project.input_kind] || project.input_kind}</span>
            <span className="pj-sep" aria-hidden="true" />
            <span>{project.src_lang === project.tgt_lang ? langName(project.tgt_lang) : `${langName(project.src_lang)} → ${langName(project.tgt_lang)}`}</span>
            {project.duration_s != null && <><span className="pj-sep" aria-hidden="true" /><span className="mono">{clock(project.duration_s)}</span></>}
          </div>
        </div>
        <div className="ed-head-right">
          {tabs}
          <CollapseButton collapse={collapse} />
        </div>
      </div>
    </header>
  );
}

// ─────────────────────────────────── Voice ─────────────────────────────────────

function VoicePicker({ project }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(null);           // voice id being applied
  const [err, setErr] = useState(null);
  const [playingId, setPlayingId] = useState(null);
  const audio = useRef(null);
  const voices = voicesFor(project.tgt_lang);
  const current = project.voice?.voice_id;
  const cur = voices.find((v) => v.id === current) || { id: current, name: current, gender: "" };

  useEffect(() => () => audio.current?.pause(), []);

  function preview(v) {
    audio.current?.pause();
    if (playingId === v.id) { setPlayingId(null); return; }
    const a = new Audio(api.voicePreviewUrl(v.id, project.tgt_lang));
    audio.current = a;
    a.onended = () => setPlayingId(null);
    a.onerror = () => { setPlayingId(null); setErr(`Couldn't play a sample of ${v.name}.`); };
    a.play().then(() => setPlayingId(v.id)).catch((e) => setErr(`Couldn't play a sample: ${e.message}`));
  }

  async function pick(v) {
    if (v.id === current || busy) return;
    if (!window.confirm(`Switch to ${v.name}? Every chunk will be re-voiced.`)) return;
    setBusy(v.id); setErr(null);
    try {
      await editor.setVoice(project.id, { mode: "persona", voice_id: v.id }, project.settings_version);
      setOpen(false);
    } catch (e) { setErr(e.message); }
    setBusy(null);
  }

  return (
    <div className="vp">
      <div className="vp-current">
        <span className={`vp-avatar vp-${(cur.gender || "x").toLowerCase()}`} aria-hidden="true">{cur.name?.[0] || "?"}</span>
        <div className="vp-id">
          <span className="vp-label">Voice</span>
          <span className="vp-name">{cur.name}</span>
          <span className="vp-meta">{[cur.gender, langName(project.tgt_lang)].filter(Boolean).join(" · ")}</span>
        </div>
        <button className="btn btn-sm" onClick={() => setOpen((o) => !o)} disabled={!!busy} aria-expanded={open}>
          {open ? "Done" : "Change voice"}
        </button>
      </div>
      {err && <p className="caption" style={{ color: "var(--red)" }}>{err}</p>}
      <AnimatePresence>
        {open && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }} style={{ overflow: "hidden" }}>
            <div className="vp-grid">
              {voices.map((v) => (
                <div key={v.id} className={`vp-card ${v.id === current ? "on" : ""}`}>
                  <button className="vp-play" onClick={() => preview(v)} aria-label={`Hear ${v.name}`}>
                    {playingId === v.id ? "❚❚" : "▶"}
                  </button>
                  <div className="vp-card-id">
                    <span className="vp-card-name">{v.name}</span>
                    <span className="vp-meta">{v.gender}</span>
                  </div>
                  {v.id === current
                    ? <span className="vp-tag">Current</span>
                    : <button className="link-btn" onClick={() => pick(v)} disabled={!!busy}>{busy === v.id ? "Switching…" : "Use"}</button>}
                </div>
              ))}
              {voices.length === 0 && <span className="dim">No voices available for {langName(project.tgt_lang)}.</span>}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ─────────────────────────────────── Chunk list ───────────────────────────────

// Generate steps as the worker reports them in project.stage (a script skips audio + transcribe).
const GEN_STEPS = [
  ["audio", "Extracting audio"],
  ["transcribe", "Transcribing speech"],
  ["chunk", "Splitting into chunks"],
  ["translate", "Translating"],
  ["voice", "Voicing chunks"],
];

function GenerateProgress({ project }) {
  const steps = GEN_STEPS.filter(([id]) => project.input_kind !== "script" || !["audio", "transcribe"].includes(id));
  const at = Math.max(0, steps.findIndex(([id]) => id === project.stage));
  return (
    <div className="progress-wrap" style={{ margin: "32px auto" }}>
      <div className="bar"><span style={{ width: `${Math.round(((at + 0.5) / steps.length) * 100)}%` }} /></div>
      <ul className="stage-list" style={{ marginTop: 20 }}>
        {steps.map(([id, name], i) => (
          <li key={id} className={`stage ${i < at ? "done" : i === at ? "on" : "pending"}`}>
            <span className="stage-icon">{i < at ? "✓" : i === at ? <Loader /> : "·"}</span>
            <span className="stage-name">{name}</span>
            <span className="stage-pct">{i < at ? "Done" : i === at ? "Working…" : ""}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ChunkList({ project, chunks }) {
  if (!chunks || chunks.length === 0) {
    if (project.status === "generating") return <GenerateProgress project={project} />;
    return <p className="dim" style={{ textAlign: "center", padding: 40 }}>No chunks yet.</p>;
  }

  const ready = chunks.filter((c) => c.status === "ready").length;
  const failed = chunks.filter((c) => c.status === "failed").length;
  const voicing = project.status === "generating" && ready + failed < chunks.length;
  return (
    <div className="editor-chunks">
      <div className="editor-chunks-head">
        <span className="body-sm dim">{chunks.length} chunk{chunks.length !== 1 ? "s" : ""}</span>
        <span className="body-sm dim">
          {voicing ? `Voicing ${ready + failed + 1} of ${chunks.length} · ` : ""}{ready} ready, {failed} failed
        </span>
      </div>
      {voicing && <div className="bar" style={{ margin: "0 0 10px" }}><span style={{ width: `${Math.round(((ready + failed) / chunks.length) * 100)}%` }} /></div>}
      {chunks.map((c) => <ChunkRow key={c.id} chunk={c} project={project} />)}
    </div>
  );
}

function ChunkRow({ chunk, project }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(chunk.text);
  const [emotion, setEmotion] = useState(chunk.emotion_tag);
  const [speed, setSpeed] = useState(chunk.speed);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  // Sync with server updates (SSE).
  useEffect(() => {
    setText(chunk.text);
    setEmotion(chunk.emotion_tag);
    setSpeed(chunk.speed);
    setErr(null);
  }, [chunk.text, chunk.emotion_tag, chunk.speed, chunk.revision]);

  const st = CHUNK_STATUS[chunk.status] || { label: chunk.status, cls: "" };
  const dirty = text !== chunk.text || emotion !== chunk.emotion_tag || parseFloat(speed) !== parseFloat(chunk.speed);

  async function save() {
    if (!dirty || busy) return;
    setBusy(true); setErr(null);
    const changes = {};
    if (text !== chunk.text) changes.text = text;
    if (emotion !== chunk.emotion_tag) changes.emotion_tag = emotion;
    if (parseFloat(speed) !== parseFloat(chunk.speed)) changes.speed = parseFloat(speed);
    try {
      await editor.editChunk(project.id, chunk.id, chunk.revision, changes);
      setEditing(false);
    } catch (e) { setErr(e.message); }
    setBusy(false);
  }

  async function regen() {
    setBusy(true); setErr(null);
    try { await editor.regenerateChunk(project.id, chunk.id); }
    catch (e) { setErr(e.message); }
    setBusy(false);
  }

  const meta = (
    <>
      <span className={`chunk-pill ${st.cls}`}>{st.label}</span>
      {chunk.anchor_src_s != null && (
        <span className="mono chunk-time">
          {clock(Number(chunk.anchor_src_s))}–{clock(Number(chunk.anchor_src_s) + Number(chunk.anchor_len_s))}
        </span>
      )}
      {chunk.emotion_tag && chunk.emotion_tag !== "neutral" && <span className="chunk-tag">{chunk.emotion_tag}</span>}
      {Number(chunk.speed) !== 1 && <span className="chunk-tag mono">{Number(chunk.speed).toFixed(2)}×</span>}
      {chunk.overflow && <span className="editor-chunk-overflow" title="Placed past the end of the video">Past video end</span>}
    </>
  );
  return (
    <div className={`editor-chunk ck ${st.cls} ${editing ? "ck-editing" : ""}`}>
      {/* One compact row: number · status/time · text (+ original) · player · edit */}
      <div className="ck-row">
        <span className="ck-idx mono">{chunk.idx + 1}</span>
        <div className="ck-meta">{meta}</div>
        <div className="ck-text">
          {!editing && <p className="editor-chunk-text">{chunk.text}</p>}
          {!editing && chunk.source_text !== chunk.text && <p className="editor-chunk-source">Original: {chunk.source_text}</p>}
          {editing && <p className="editor-chunk-text ck-editing-label">Editing chunk {chunk.idx + 1}</p>}
        </div>
        <div className="ck-side">
          {chunk.status === "ready" && chunk.has_audio && !editing && (
            <AudioPlayer key={chunk.revision} label={`Chunk ${chunk.idx + 1}`} compact
                         src={() => editor.chunkAudioUrl(project.id, chunk.id).then((r) => r.url)} onError={setErr} />
          )}
          {(chunk.status === "pending" || chunk.status === "generating") && (
            <span className="chunk-wait"><Loader size={14} /> Generating…</span>
          )}
          {chunk.status === "failed" && (
            <button className="btn btn-quiet btn-xs" onClick={regen} disabled={busy}>Retry</button>
          )}
          <button className="btn btn-quiet btn-xs" onClick={() => setEditing((e) => !e)} disabled={busy}>
            {editing ? "Cancel" : "Edit"}
          </button>
        </div>
      </div>

      {editing && (
        <div className="editor-chunk-edit">
          <textarea className="input" rows={3} value={text} onChange={(e) => setText(e.target.value)}
                    disabled={busy} style={{ resize: "vertical" }} aria-label="Chunk text" />
          <div className="chunk-edit-row">
            <label className="ne-field-inline">Emotion
              <select className="select select-sm" value={emotion} onChange={(e) => setEmotion(e.target.value)} disabled={busy}>
                {EMOTION_TAGS.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            <label className="ne-field-inline">Speed
              <input type="number" className="input input-sm" value={speed} min={0.5} max={2} step={0.05}
                     onChange={(e) => setSpeed(e.target.value)} disabled={busy} style={{ width: 84 }} />
            </label>
            <span style={{ flex: 1 }} />
            <button className="btn btn-primary btn-sm" onClick={save} disabled={!dirty || busy}>
              {busy ? "Saving…" : "Save and re-voice"}
            </button>
          </div>
          <p className="caption">Only this chunk is re-voiced, with the project's voice ({project.voice?.voice_id}).</p>
        </div>
      )}

      {chunk.error_message && <p className="chunk-err" role="alert">{chunk.error_message}</p>}
      {err && <p className="chunk-err" role="alert">{err}</p>}
    </div>
  );
}
