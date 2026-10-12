import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import * as editor from "../lib/editorApi.js";
import { TARGET_LANGS, VOICES, langName, voicesFor } from "../lib/catalog.js";
import { clock } from "../lib/format.js";

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
  const nav = useNavigate();
  const [data, setData] = useState(null);           // { project, chunks }
  const [error, setError] = useState(null);
  const [sseOk, setSseOk] = useState(false);

  // Fetch once, then let SSE drive updates.
  useEffect(() => {
    let cancelled = false;
    editor.getProject(id)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [id]);

  // SSE subscription — reconnects automatically.
  useEffect(() => {
    const unsub = editor.subscribe(id, {
      onSnapshot(snap) { setData(snap); setSseOk(true); },
      onError(e) { setError(e.message || "Live update error."); },
      onHeartbeat() { setSseOk(true); },
    });
    return unsub;
  }, [id]);

  if (error && !data) {
    return (
      <section className="page empty">
        <h1 className="title">Project not found</h1>
        <p>{error}</p>
        <Link to="/projects">Back to projects</Link>
      </section>
    );
  }

  if (!data) {
    return <div className="progress-wrap"><div className="spinner" style={{ margin: "0 auto" }} /></div>;
  }

  const { project, chunks } = data;

  return (
    <>
      <ProjectHeader project={project} onDelete={() => { editor.deleteProject(id).then(() => nav("/projects")); }} />
      {project.error_message && (
        <section className="page" style={{ paddingTop: 0, paddingBottom: 0 }}>
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
        <section className="page" style={{ paddingTop: 0, paddingBottom: 0 }}>
          <div className="banner error" role="alert"><span className="banner-dot" /><span>{error}</span></div>
        </section>
      )}
      <section className="page" style={{ paddingTop: 0 }}>
        <VoicePicker project={project} />
        <ChunkList project={project} chunks={chunks} />
      </section>
    </>
  );
}

// ─────────────────────────────────── Header ───────────────────────────────────

function ProjectHeader({ project, onDelete }) {
  return (
    <section className="page" style={{ paddingBottom: 8 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 16, flexWrap: "wrap" }}>
        <Link to="/projects" className="body-sm dim" style={{ textDecoration: "none" }}>← Projects</Link>
        <h1 className="title" style={{ margin: 0 }}>{project.name}</h1>
        <span className={`status-pill status-${project.status}`}>{STATUS_LABEL[project.status] || project.status}</span>
      </div>
      <div className="body-sm dim" style={{ marginTop: 6, display: "flex", gap: 16, flexWrap: "wrap" }}>
        <span>{langName(project.src_lang)} → {langName(project.tgt_lang)}</span>
        {project.duration_s != null && <span>{clock(project.duration_s)}</span>}
        <span>{project.input_kind.replace("_", " + ")}</span>
        <button className="link-btn dim" style={{ fontSize: 13 }} onClick={onDelete}>Delete</button>
      </div>
    </section>
  );
}

// ─────────────────────────────────── Voice ─────────────────────────────────────

function VoicePicker({ project }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const voices = voicesFor(project.tgt_lang);
  const current = project.voice?.voice_id || voices[0]?.id;

  async function pick(voiceId) {
    if (voiceId === current || busy) return;
    setBusy(true); setErr(null);
    try {
      await editor.setVoice(project.id, { mode: "persona", voice_id: voiceId }, project.settings_version);
      setOpen(false);
    } catch (e) { setErr(e.message); }
    setBusy(false);
  }

  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span className="field-label" style={{ margin: 0 }}>Voice</span>
        <span className="mono" style={{ fontWeight: 600 }}>{current}</span>
        <button className="link-btn" onClick={() => setOpen((o) => !o)} disabled={busy}>
          {open ? "Close" : "Change voice"}
        </button>
      </div>
      {err && <p className="caption" style={{ color: "var(--red)" }}>{err}</p>}
      <AnimatePresence>
        {open && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }} style={{ overflow: "hidden" }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
              {voices.map((v) => (
                <button key={v.id} className={`chip-btn ${v.id === current ? "on" : ""}`}
                        onClick={() => pick(v.id)} disabled={busy}>
                  {v.name} <small>{v.gender}</small>
                </button>
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

function ChunkList({ project, chunks }) {
  if (!chunks || chunks.length === 0) {
    if (project.status === "generating") {
      return <p className="dim" style={{ textAlign: "center", padding: 40 }}>Generating chunks…</p>;
    }
    return <p className="dim" style={{ textAlign: "center", padding: 40 }}>No chunks yet.</p>;
  }

  return (
    <div className="editor-chunks">
      <div className="editor-chunks-head">
        <span className="body-sm dim">{chunks.length} chunk{chunks.length !== 1 ? "s" : ""}</span>
        <span className="body-sm dim">
          {chunks.filter((c) => c.status === "ready").length} ready,{" "}
          {chunks.filter((c) => c.status === "failed").length} failed
        </span>
      </div>
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
  const [audioUrl, setAudioUrl] = useState(null);

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

  async function playAudio() {
    try {
      const { url } = await editor.chunkAudioUrl(project.id, chunk.id);
      setAudioUrl(url);
    } catch (e) { setErr(e.message); }
  }

  return (
    <div className={`editor-chunk ${st.cls}`}>
      <div className="editor-chunk-head">
        <span className="editor-chunk-idx mono">{chunk.idx + 1}</span>
        <span className={`editor-chunk-status ${st.cls}`}>{st.label}</span>
        {chunk.anchor_src_s != null && (
          <span className="mono dim" style={{ fontSize: 12 }}>
            {Number(chunk.anchor_src_s).toFixed(1)}s – {(Number(chunk.anchor_src_s) + Number(chunk.anchor_len_s)).toFixed(1)}s
          </span>
        )}
        {chunk.overflow && <span className="editor-chunk-overflow" title="Past the end of the video">⚠ overflow</span>}
        <span style={{ flex: 1 }} />
        {chunk.status === "ready" && chunk.has_audio && (
          <button className="link-btn" onClick={playAudio} style={{ fontSize: 12 }}>▶ Play</button>
        )}
        {(chunk.status === "ready" || chunk.status === "failed") && (
          <button className="link-btn" onClick={regen} disabled={busy} style={{ fontSize: 12 }}>
            {chunk.status === "failed" ? "Retry" : "Regenerate"}
          </button>
        )}
        <button className="link-btn" onClick={() => setEditing((e) => !e)} style={{ fontSize: 12 }}>
          {editing ? "Cancel" : "Edit"}
        </button>
      </div>

      {audioUrl && (
        <audio src={audioUrl} controls autoPlay style={{ width: "100%", height: 32, marginTop: 4 }}
               onEnded={() => setAudioUrl(null)} />
      )}

      {chunk.error_message && (
        <p className="caption" style={{ color: "var(--red)", margin: "4px 0" }}>{chunk.error_message}</p>
      )}

      {!editing ? (
        <p className="editor-chunk-text">{chunk.text}</p>
      ) : (
        <div className="editor-chunk-edit">
          <textarea className="input" rows={3} value={text} onChange={(e) => setText(e.target.value)}
                    disabled={busy} style={{ resize: "vertical" }} />
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 6 }}>
            <label className="body-sm">Emotion:
              <select className="select" value={emotion} onChange={(e) => setEmotion(e.target.value)}
                      disabled={busy} style={{ marginLeft: 6, width: "auto" }}>
                {EMOTION_TAGS.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            <label className="body-sm">Speed:
              <input type="number" className="input" value={speed} min={0.85} max={1.15} step={0.05}
                     onChange={(e) => setSpeed(e.target.value)} disabled={busy}
                     style={{ width: 70, marginLeft: 6 }} />
            </label>
            <button className="btn btn-primary btn-sm" onClick={save} disabled={!dirty || busy}>
              {busy ? "Saving…" : "Save & regenerate"}
            </button>
          </div>
          {err && <p className="caption" style={{ color: "var(--red)", marginTop: 4 }}>{err}</p>}
        </div>
      )}

      {!editing && chunk.source_text !== chunk.text && (
        <p className="editor-chunk-source dim" style={{ fontSize: 12, marginTop: 2 }}>
          Source: {chunk.source_text}
        </p>
      )}
    </div>
  );
}
