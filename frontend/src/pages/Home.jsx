import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { api } from "../lib/api.js";
import { SOURCE_LANGS, TARGET_LANGS } from "../lib/catalog.js";
import { bytes, clock } from "../lib/format.js";
import { Arrow, UploadIcon } from "../components/Icons.jsx";

const MAX_BYTES = 500e6;
const MAX_SECONDS = 600;
const ACCEPT = "video/mp4,video/quicktime,video/webm,video/x-matroska,.mkv";

function probe(file) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const v = document.createElement("video");
    v.preload = "metadata";
    v.onloadedmetadata = () => resolve({ url, duration: v.duration });
    v.onerror = () => resolve({ url, duration: null });
    v.src = url;
  });
}

export default function Home({ mode: apiMode }) {
  const nav = useNavigate();
  const inputRef = useRef(null);
  const [drag, setDrag] = useState(false);
  const [file, setFile] = useState(null);
  const [meta, setMeta] = useState(null);
  const [mode, setMode] = useState("dub");   // dub | narrate
  const [src, setSrc] = useState("auto");
  const [tgt, setTgt] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [upload, setUpload] = useState(0);
  const [hl, setHl] = useState(0);

  useEffect(() => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = setInterval(() => setHl((h) => (h + 1) % 6), 1600);
    return () => clearInterval(id);
  }, []);

  async function accept(f) {
    setError(null);
    if (!f) return;
    if (!f.type.startsWith("video/") && !/\.(mkv|mov|mp4|webm)$/i.test(f.name)) {
      setError("That file isn't a video. Choose an MP4, MOV, WebM or MKV file.");
      return;
    }
    if (f.size > MAX_BYTES) {
      setError(`That video is ${bytes(f.size)}. The limit is 500 MB.`);
      return;
    }
    const m = await probe(f);
    if (m.duration && m.duration > MAX_SECONDS) {
      setError(`That video is ${clock(m.duration)} long. The limit is 10 minutes.`);
      return;
    }
    setFile(f);
    setMeta(m);
  }

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const job = await api.createJob(file, src, tgt, setUpload, mode);
      nav(`/jobs/${job.id}`);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  const showcase = ["हिन्दी", "தமிழ்", "తెలుగు", "ಕನ್ನಡ", "বাংলা", "മലയാളം"];

  return (
    <>
      <section className="hero page">
        <motion.h1 className="headline" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }}>
          Your video. Every Indian language.
        </motion.h1>
        <motion.p className="lead" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.2, duration: 0.6 }}>
          Upload a video and get it back dubbed, with every line on time and the feeling of the original voice intact.
        </motion.p>
        <p className="hero-langs" aria-hidden="true">
          {showcase.map((l, i) => (
            <span key={l} className={i === hl ? "on" : ""} style={{ margin: "0 12px" }}>{l}</span>
          ))}
        </p>
      </section>

      <section className="page" style={{ paddingBottom: 40 }}>
        {apiMode === "demo" && (
          <div className="banner" style={{ marginBottom: 20 }}>
            <span className="banner-dot" />
            <span><b>Demo mode.</b> The backend isn't running, so the pipeline is simulated with sample lines and your video is returned undubbed. Nothing is uploaded and no credits are used.</span>
          </div>
        )}

        {!file ? (
          <div
            className={`dropzone ${drag ? "drag" : ""}`}
            role="button" tabIndex={0}
            onClick={() => inputRef.current?.click()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); accept(e.dataTransfer.files[0]); }}
          >
            <UploadIcon className="dropzone-icon" />
            <div>
              <p className="subhead">Drop a video here</p>
              <p className="muted" style={{ marginTop: 6 }}>or <span style={{ color: "var(--blue)" }}>choose a file</span>. MP4, MOV, WebM or MKV, up to 10 minutes.</p>
            </div>
            <input ref={inputRef} type="file" accept={ACCEPT} hidden onChange={(e) => accept(e.target.files[0])} />
          </div>
        ) : (
          <motion.div className="stack" style={{ gap: 28 }} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
            <div className="file-row">
              <video src={meta?.url} muted playsInline preload="metadata" />
              <div className="file-meta">
                <span className="file-name">{file.name}</span>
                <span className="body-sm dim">{bytes(file.size)}{meta?.duration ? `, ${clock(meta.duration)}` : ""}</span>
              </div>
              <button className="link-btn body-sm" onClick={() => { setFile(null); setMeta(null); setTgt(null); }} disabled={busy}>
                Replace
              </button>
            </div>

            <div className="field">
              <span className="field-label" id="mode-label">What do you want to do?</span>
              <div className="mode-cards" role="radiogroup" aria-labelledby="mode-label">
                <button className="mode-card" role="radio" aria-checked={mode === "dub"} disabled={busy}
                        onClick={() => { setMode("dub"); if (tgt === "same") setTgt(null); }}>
                  <span className="mode-title">Dub the speech in this video</span>
                  <span className="mode-sub">We transcribe what's said and re-voice it in another language.</span>
                </button>
                <button className="mode-card" role="radio" aria-checked={mode === "narrate"} disabled={busy}
                        onClick={() => setMode("narrate")}>
                  <span className="mode-title">Narrate it yourself</span>
                  <span className="mode-sub">Record your voice while the video plays. Keep it, or have it re-voiced or translated.</span>
                </button>
              </div>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="src">{mode === "dub" ? "Spoken language in the video" : "Language you'll speak in"}</label>
              <select id="src" className="select" value={src} onChange={(e) => setSrc(e.target.value)} disabled={busy}>
                {SOURCE_LANGS.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
              </select>
            </div>

            <div className="field">
              <span className="field-label" id="tgt-label">{mode === "dub" ? "Dub it into" : "Final narration language"}</span>
              <div className="target-chips" role="group" aria-labelledby="tgt-label">
                {mode === "narrate" && (
                  <button className="chip-btn" aria-pressed={tgt === "same"} onClick={() => setTgt("same")} disabled={busy}>
                    Same as I speak
                  </button>
                )}
                {TARGET_LANGS.map((l) => (
                  <button key={l.code} className="chip-btn" aria-pressed={tgt === l.code} onClick={() => setTgt(l.code)} disabled={busy}>
                    {l.name}{l.native !== l.name && <small>{l.native}</small>}
                  </button>
                ))}
              </div>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap" }}>
              <button className="btn btn-primary" disabled={!tgt || busy} onClick={start}>
                {busy ? (upload > 0 && upload < 1 ? `Uploading ${Math.round(upload * 100)}%` : "Starting…") : mode === "dub" ? "Transcribe video" : "Start narrating"}
                {!busy && <Arrow />}
              </button>
              <span className="body-sm dim">
                {mode === "dub"
                  ? "You'll review the transcript and pick a voice before anything is dubbed."
                  : "Next you'll record over the video. You can re-record as often as you like."}
              </span>
            </div>
          </motion.div>
        )}

        {error && (
          <div className="banner error" role="alert" style={{ marginTop: 20 }}>
            <span className="banner-dot" /><span>{error}</span>
          </div>
        )}
      </section>

      <section className="section page">
        <h2 className="title" style={{ marginBottom: 32 }}>How it works</h2>
        <div className="how">
          <div className="card">
            <p className="how-k">Step 1</p>
            <h3>Transcribe and review</h3>
            <p>Every line is found with its exact timing and the emotion it was spoken with. Fix anything before it's dubbed.</p>
          </div>
          <div className="card">
            <p className="how-k">Step 2</p>
            <h3>Choose a voice</h3>
            <p>Pick from 42 natural Indian voices, or keep the speaker's own voice with a clone, with their consent.</p>
          </div>
          <div className="card">
            <p className="how-k">Step 3</p>
            <h3>Get it back in sync</h3>
            <p>Each line starts exactly where the original did, and the video comes back the same length, down to the sample.</p>
          </div>
        </div>
      </section>
    </>
  );
}
