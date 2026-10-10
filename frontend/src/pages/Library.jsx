import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { addVideos, refreshLibrary, removeVideo, useLibrary } from "../lib/libraryStore.js";
import { langName } from "../lib/catalog.js";
import { ago, bytes, clock } from "../lib/format.js";

const ACCEPT = "video/mp4,video/quicktime,video/webm,video/x-matroska,.mkv";

const STATUS_LABEL = {
  INITIATED: "Waiting…",
  UPLOADED: "Waiting…",
  PROCESSING: "Processing…",
  FAILED: "Failed",
};

export default function Library() {
  const nav = useNavigate();
  const input = useRef(null);
  const library = useLibrary();
  const [q, setQ] = useState("");
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null); // { name, phase, pct } while an upload runs

  useEffect(() => { refreshLibrary(); }, []);

  const items = useMemo(() => {
    const s = q.trim().toLowerCase();
    return s ? library.filter((v) => v.name.toLowerCase().includes(s)) : library;
  }, [library, q]);

  async function add(files) {
    setError(null);
    const { errors } = await addVideos(files, (name, phase, pct) =>
      setBusy({ name, phase, pct: phase === "upload" ? Math.round((pct || 0) * 100) : null }));
    setBusy(null);
    if (errors.length) setError(errors.join(" "));
  }

  return (
    <div className="page-wide lib-page">
      <div className="pg-head">
        <div>
          <h1 className="title">Library</h1>
          <p className="muted" style={{ marginTop: 6 }}>Your uploaded videos, ready to dub or narrate.</p>
        </div>
        <div className="pg-actions">
          <input className="input search" type="search" placeholder="Search videos" value={q} onChange={(e) => setQ(e.target.value)}
                 aria-label="Search videos" />
          <button className="btn btn-primary" onClick={() => input.current?.click()}>Upload videos</button>
          <input ref={input} type="file" accept={ACCEPT} multiple hidden onChange={(e) => { add([...e.target.files]); e.target.value = ""; }} />
        </div>
      </div>

      <div className="banner" style={{ marginBottom: 24 }}>
        <span className="banner-dot" />
        <span><b>Library.</b> Uploaded videos are processed in the background (thumbnail &amp; preview) and saved to your account — they survive a page refresh. Processing usually takes a minute or two.</span>
      </div>

      {error && <div className="banner error" role="alert" style={{ marginBottom: 20 }}><span className="banner-dot" /><span>{error}</span></div>}

      {busy && (
        <div className="banner" role="status" style={{ marginBottom: 20 }}>
          <span className="banner-dot" />
          <span style={{ flex: 1 }}>
            {busy.phase === "upload" ? `Uploading ${busy.name}… ${busy.pct ?? 0}%`
              : busy.phase === "finalize" ? `Finalizing ${busy.name}…`
              : `Preparing ${busy.name}…`}
            <span style={{ display: "block", marginTop: 8, height: 6, background: "rgba(127,127,127,.25)", borderRadius: 4, overflow: "hidden" }}>
              <span style={{ display: "block", height: "100%", borderRadius: 4, transition: "width .2s", background: "currentColor",
                             width: `${busy.phase === "upload" ? busy.pct ?? 0 : busy.phase === "finalize" ? 100 : 4}%` }} />
            </span>
          </span>
        </div>
      )}

      <div className={`lib-drop ${drag ? "drag" : ""}`}
           onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
           onDragLeave={() => setDrag(false)}
           onDrop={(e) => { e.preventDefault(); setDrag(false); add([...e.dataTransfer.files]); }}>
        <div className="lib-grid">
          <AnimatePresence initial={false}>
            {items.map((v) => (
              <motion.article key={v.id} className="lib-card" layout
                              initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.97 }}
                              transition={{ duration: 0.25 }}>
                <div className="lib-thumb" style={v.local || v.cover ? { background: v.cover } : undefined}>
                  {v.local && <video src={v.url} muted playsInline preload="metadata" />}
                  {v.duration_s && <span className="lib-dur mono">{clock(v.duration_s)}</span>}
                  {v.local && <span className="lib-badge">Not saved</span>}
                  {v.remote && v.status && v.status !== "READY" && (
                    <span className="lib-badge">{STATUS_LABEL[v.status] || v.status}</span>
                  )}
                </div>
                <div className="lib-info">
                  <span className="lib-name" title={v.name}>{v.name}</span>
                  <span className="lib-meta">
                    {bytes(v.size)}{v.lang ? `, ${langName(v.lang)}` : ""}, {ago(v.uploaded_at)}
                  </span>
                </div>
                <div className="lib-actions">
                  <button className="btn btn-quiet btn-sm" disabled={!v.local}
                          title={v.local ? undefined : v.remote ? "Start a project once this video is ready." : "Sample item. Upload a video to use it."}
                          onClick={() => nav("/new", { state: { libraryId: v.id } })}>
                    New project
                  </button>
                  {(v.local || v.remote) && (
                    <button className="link-btn body-sm" onClick={() => removeVideo(v.id)}>Remove</button>
                  )}
                </div>
              </motion.article>
            ))}
          </AnimatePresence>
        </div>
        {items.length === 0 && <p className="muted" style={{ textAlign: "center", padding: 48 }}>No videos match “{q}”.</p>}
      </div>
    </div>
  );
}
