import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { addVideos, removeVideo, useLibrary } from "../lib/libraryStore.js";
import { langName } from "../lib/catalog.js";
import { ago, bytes, clock } from "../lib/format.js";

const ACCEPT = "video/mp4,video/quicktime,video/webm,video/x-matroska,.mkv";


export default function Library() {
  const nav = useNavigate();
  const input = useRef(null);
  const library = useLibrary();
  const [q, setQ] = useState("");
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState(null);

  const items = useMemo(() => {
    const s = q.trim().toLowerCase();
    return s ? library.filter((v) => v.name.toLowerCase().includes(s)) : library;
  }, [library, q]);

  async function add(files) {
    setError(null);
    const { errors } = await addVideos(files);
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
        <span><b>Preview.</b> Library storage isn't connected yet. The sample videos below are placeholders, and videos you upload stay available until the page is refreshed.</span>
      </div>

      {error && <div className="banner error" role="alert" style={{ marginBottom: 20 }}><span className="banner-dot" /><span>{error}</span></div>}

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
                <div className="lib-thumb" style={v.local ? undefined : { background: v.cover }}>
                  {v.local && <video src={v.url} muted playsInline preload="metadata" />}
                  {v.duration_s && <span className="lib-dur mono">{clock(v.duration_s)}</span>}
                  {v.local && <span className="lib-badge">Not saved</span>}
                </div>
                <div className="lib-info">
                  <span className="lib-name" title={v.name}>{v.name}</span>
                  <span className="lib-meta">
                    {bytes(v.size)}{v.lang ? `, ${langName(v.lang)}` : ""}, {ago(v.uploaded_at)}
                  </span>
                </div>
                <div className="lib-actions">
                  <button className="btn btn-quiet btn-sm" disabled={!v.local}
                          title={v.local ? undefined : "Sample item. Upload a video to use it."}
                          onClick={() => nav("/new", { state: { libraryId: v.id } })}>
                    New project
                  </button>
                  {v.local && (
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
