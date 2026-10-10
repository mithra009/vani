import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "../lib/api.js";
import { SOURCE_LANGS, TARGET_LANGS, langName } from "../lib/catalog.js";
import { addVideos, stripExt, useLibrary } from "../lib/libraryStore.js";
import { ago, bytes, clock } from "../lib/format.js";
import { Arrow, Check } from "../components/Icons.jsx";

const ACCEPT = "video/mp4,video/quicktime,video/webm,video/x-matroska,.mkv";

const SLIDE = {
  enter: (d) => ({ opacity: 0, x: d * 48 }),
  center: { opacity: 1, x: 0, transition: { duration: 0.32, ease: [0.28, 0.11, 0.32, 1] } },
  exit: (d) => ({ opacity: 0, x: d * -48, transition: { duration: 0.2 } }),
};

export default function NewProject({ mode: apiMode }) {
  const nav = useNavigate();
  const loc = useLocation();
  const library = useLibrary();
  const uploadRef = useRef(null);

  const [selectedId, setSelectedId] = useState(loc.state?.libraryId || null);
  const [step, setStep] = useState(loc.state?.libraryId ? 1 : 0);
  const [dir, setDir] = useState(1);
  const [name, setName] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [mode, setMode] = useState("dub");   // dub | narrate
  const [src, setSrc] = useState("auto");
  const [tgt, setTgt] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [upload, setUpload] = useState(0);

  const selected = library.find((v) => v.id === selectedId && v.file);
  const usable = library.filter((v) => v.file);
  const samples = library.filter((v) => !v.file);

  // The name follows the chosen video until the user edits it.
  useEffect(() => {
    if (selected && !nameTouched) setName(stripExt(selected.name));
  }, [selected, nameTouched]);

  const go = (to) => { setDir(to > step ? 1 : -1); setStep(to); };
  const choose = (id) => { setSelectedId(id); setDir(1); setStep(1); };

  async function uploadToLibrary(files) {
    setError(null);
    const { added, errors } = await addVideos(files);
    if (errors.length) setError(errors.join(" "));
    if (added[0]) choose(added[0].id);
  }

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const projectName = name.trim() || stripExt(selected.name);
      const job = await api.createJob(selected.file, src, tgt, setUpload, mode, projectName);
      nav(`/jobs/${job.id}`);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <>
      <section className="page new-head">
        <motion.h1 className="title" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>New project</motion.h1>
        <p className="lead" style={{ marginTop: 10 }}>Pick a video from your library, then dub its speech or narrate it yourself.</p>
      </section>

      <section className="page" style={{ paddingBottom: 60 }}>
        {apiMode === "demo" && (
          <div className="banner" style={{ marginBottom: 24 }}>
            <span className="banner-dot" />
            <span><b>Demo mode.</b> The backend isn't running, so the pipeline is simulated and your video is returned undubbed. No credits are used.</span>
          </div>
        )}

        {/* ---------- two slides: pick a video, then details ---------- */}
        <div className="np-dots" role="tablist" aria-label="New project steps">
          {["Video", "Details"].map((label, i) => (
            <button key={label} role="tab" aria-selected={step === i} aria-label={`Step ${i + 1}: ${label}`}
                    className={`np-dot ${step === i ? "on" : ""}`} disabled={i === 1 && !selected || busy}
                    onClick={() => go(i)}>
              <span className="np-dot-mark" />
              <span className="np-dot-label">{label}</span>
            </button>
          ))}
        </div>

        <div className="np-slides">
          <AnimatePresence mode="wait" initial={false} custom={dir}>
            {step === 0 ? (
              <motion.div key="pick" className="np-slide" custom={dir} variants={SLIDE}
                          initial="enter" animate="center" exit="exit">
              <div className="np-step">
                <div className="np-step-head">
                  <h2 className="np-h">Choose a video</h2>
                  <div className="np-step-actions">
                    <button className="link-btn" style={{ fontSize: 14 }} onClick={() => uploadRef.current?.click()} disabled={busy}>Upload to library</button>
                    <input ref={uploadRef} type="file" accept={ACCEPT} multiple hidden
                           onChange={(e) => { uploadToLibrary([...e.target.files]); e.target.value = ""; }} />
                    <Link to="/library" className="body-sm">Open library</Link>
                  </div>
                </div>

                {usable.length === 0 && (
                  <div className="np-empty">
                    <p>Your library has no videos you can use yet.</p>
                    <button className="btn btn-primary btn-sm" onClick={() => uploadRef.current?.click()}>Upload a video</button>
                  </div>
                )}

                <div className="np-grid" role="radiogroup" aria-label="Library videos">
                  {[...usable, ...samples].map((v) => {
                    const disabled = !v.file || busy;
                    const on = v.id === selectedId && !!v.file;
                    return (
                      <button key={v.id} className={`np-video ${on ? "on" : ""}`} role="radio" aria-checked={on} disabled={disabled}
                              onClick={() => choose(v.id)}
                              title={v.file ? v.name : "Sample video, no file. Upload a video to use it."}>
                        <span className="np-thumb" style={v.file ? undefined : { background: v.cover }}>
                          {v.file && <video src={v.url} muted playsInline preload="metadata" />}
                          {v.duration_s && <span className="lib-dur mono">{clock(v.duration_s)}</span>}
                          {!v.file && <span className="np-sample">Sample</span>}
                          {on && <span className="np-check"><Check size={22} color="var(--blue)" /></span>}
                        </span>
                        <span className="np-vname">{v.name}</span>
                        <span className="np-vmeta">{bytes(v.size)}{v.lang ? `, ${langName(v.lang)}` : ""}, {ago(v.uploaded_at)}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
              </motion.div>
            ) : (
              <motion.div key="details" className="np-slide" custom={dir} variants={SLIDE}
                          initial="enter" animate="center" exit="exit">
                <div className="np-details">
                  <div className="np-col">
                  <div className="np-picked">
                    <span className="np-picked-thumb">
                      <video src={selected.url} muted playsInline preload="metadata" />
                    </span>
                    <span className="np-picked-info">
                      <span className="np-picked-label">Video</span>
                      <span className="np-picked-name" title={selected.name}>{selected.name}</span>
                      <span className="np-vmeta">{bytes(selected.size)}{selected.duration_s ? `, ${clock(selected.duration_s)}` : ""}</span>
                    </span>
                    <button className="link-btn np-change" onClick={() => go(0)} disabled={busy}>Change</button>
                  </div>

                  <div className="field">
                    <label className="field-label" htmlFor="pname">Project name <span className="dim">(optional)</span></label>
                    <input id="pname" className="input" value={name} maxLength={120} disabled={busy}
                           placeholder={stripExt(selected.name)}
                           onChange={(e) => { setName(e.target.value); setNameTouched(true); }} />
                    <p className="caption">Defaults to the video's name.</p>
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

                  </div>
                  <div className="np-col">
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
                      {busy ? (upload > 0 && upload < 1 ? `Uploading ${Math.round(upload * 100)}%` : "Creating project…")
                        : mode === "dub" ? "Create and transcribe" : "Create and start narrating"}
                      {!busy && <Arrow />}
                    </button>
                    <span className="body-sm dim">
                      {mode === "dub"
                        ? "You'll review the transcript and pick a voice before anything is dubbed."
                        : "Next you'll record over the video. You can re-record as often as you like."}
                    </span>
                  </div>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {error && (
          <div className="banner error" role="alert" style={{ marginTop: 20 }}>
            <span className="banner-dot" /><span>{error}</span>
          </div>
        )}
      </section>
    </>
  );
}
