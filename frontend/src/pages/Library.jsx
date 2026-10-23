import { useEffect, useMemo, useRef, useState } from "react";
import { Loader } from "../components/Icons.jsx";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "../lib/api.js";
import { addVideos, refreshLibrary, removeVideo, useLibrary } from "../lib/libraryStore.js";
import { langName } from "../lib/catalog.js";
import { ago, bytes, clock } from "../lib/format.js";
import InfoTip from "../components/InfoTip.jsx";
import { toast } from "../lib/toast.jsx";

const ACCEPT = "video/mp4,video/quicktime,video/webm,video/x-matroska,.mkv";

const STATUS_LABEL = {
  INITIATED: "Waiting…",
  UPLOADED: "Waiting…",
  PROCESSING: "Processing…",
  FAILED: "Failed",
};

const Svg = ({ children, size = 18 }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.7"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);
const EyeIcon = () => <Svg><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" /><circle cx="12" cy="12" r="3" /></Svg>;
const BinIcon = () => <Svg><path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13M10 11v5.5M14 11v5.5" /></Svg>;

function PlayIcon() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="currentColor">
      <path d="M8 5.14v13.72c0 .8.87 1.3 1.56.88l11.03-6.86c.65-.4.65-1.35 0-1.76L9.56 4.26A1.02 1.02 0 0 0 8 5.14Z" />
    </svg>
  );
}

export default function Library() {
  const nav = useNavigate();
  const input = useRef(null);
  const library = useLibrary();
  const [q, setQ] = useState("");
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(null); // { name, phase, pct } while an upload runs
  const [preview, setPreview] = useState(null); // { name, url, loading } while a player is open
  const [removing, setRemoving] = useState(null); // video awaiting confirmation

  useEffect(() => { refreshLibrary(); }, []);

  // Close the preview on Escape.
  useEffect(() => {
    if (!preview) return;
    const onKey = (e) => e.key === "Escape" && setPreview(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [preview]);

  /** Local items play their object URL; cloud items get a fresh signed proxy URL. */
  async function openPreview(v) {
    if (v.local) {
      setPreview({ name: v.name, url: v.url });
      return;
    }
    setPreview({ name: v.name, url: null, loading: true });
    try {
      const { url } = await api.assetPreviewUrl(v.id);
      setPreview({ name: v.name, url });
    } catch (e) {
      setPreview(null);
      toast.error(`Preview unavailable: ${e.message}`);
    }
  }

  const items = useMemo(() => {
    const s = q.trim().toLowerCase();
    return s ? library.filter((v) => v.name.toLowerCase().includes(s)) : library;
  }, [library, q]);

  async function add(files) {
    const { errors } = await addVideos(files, (name, phase, pct) =>
      setBusy({ name, phase, pct: phase === "upload" ? Math.round((pct || 0) * 100) : null }));
    setBusy(null);
    errors.forEach((m) => toast.error(m));
  }

  return (
    <div className="page-wide lib-page">
      <div className="pg-head">
        <div>
          <div className="pg-title-row">
            <h1 className="pg-title">Library</h1>
            <InfoTip label="About the Library">
              <p><b>Your videos, stored in your account.</b> Upload once and start any number of projects from the same video.</p>
              <p>After upload, each video gets a thumbnail and a fast preview copy. That takes a minute or two; you can keep working meanwhile.</p>
              <p className="caption">MP4, MOV, WebM or MKV · up to 500 MB · up to 10 minutes.</p>
            </InfoTip>
          </div>
          <p className="pg-sub">Your uploaded videos, ready to dub, script or narrate.</p>
        </div>
        <div className="pg-actions">
          <input className="input search" type="search" placeholder="Search videos" value={q} onChange={(e) => setQ(e.target.value)}
                 aria-label="Search videos" />
          <button className="btn btn-primary btn-ctl" onClick={() => input.current?.click()}>Upload videos</button>
          <input ref={input} type="file" accept={ACCEPT} multiple hidden onChange={(e) => { add([...e.target.files]); e.target.value = ""; }} />
        </div>
      </div>

      {busy && (
        <div className="banner" role="status" style={{ marginBottom: 20 }}>
          <Loader size={16} />
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
                    <span className="lib-badge">{v.status === "PROCESSING" && <Loader size={12} />}{STATUS_LABEL[v.status] || v.status}</span>
                  )}
                  {(v.local || v.proxy_status === "READY") && (
                    <button className="lib-play" aria-label={`Preview ${v.name}`} onClick={() => openPreview(v)}>
                      <PlayIcon />
                    </button>
                  )}
                </div>
                <div className="lib-info">
                  <span className="lib-name" title={v.name}>{v.name}</span>
                  <span className="lib-meta">
                    {bytes(v.size)}{v.lang ? `, ${langName(v.lang)}` : ""}, {ago(v.uploaded_at)}
                  </span>
                </div>
                <div className="lib-actions">
                  <button className="btn btn-quiet btn-sm" disabled={!v.local && !(v.remote && v.status === "READY")}
                          title={v.local || (v.remote && v.status === "READY") ? undefined : "Available when processing finishes."}
                          onClick={() => v.remote ? nav(`/new?asset=${v.id}`) : nav("/new", { state: { libraryId: v.id } })}>
                    New project
                  </button>
                  <span className="lib-actions-gap" />
                  <button className="icon-btn" onClick={() => openPreview(v)} disabled={!(v.local || v.proxy_status === "READY")}
                          aria-label={`Preview ${v.name}`} title="Preview"><EyeIcon /></button>
                  <button className="icon-btn icon-btn-danger" onClick={() => setRemoving(v)}
                          aria-label={`Remove ${v.name}`} title="Remove from Library"><BinIcon /></button>
                </div>
              </motion.article>
            ))}
          </AnimatePresence>
        </div>
        {items.length === 0 && (q.trim()
          ? <p className="muted" style={{ textAlign: "center", padding: 48 }}>No videos match “{q}”.</p>
          : (
            <div className="lib-empty">
              <p className="pj-empty-title">No videos yet</p>
              <p className="muted body-sm">Drop a video here or upload one to start a project.</p>
              <button className="btn btn-primary btn-ctl" onClick={() => input.current?.click()}>Upload a video</button>
            </div>
          ))}
      </div>

      <AnimatePresence>
        {removing && (
          <motion.div className="modal-bg" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                      onClick={() => setRemoving(null)}>
            <motion.div className="modal" role="alertdialog" aria-modal="true" aria-labelledby="rm-h"
                        initial={{ scale: 0.96, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.96, opacity: 0 }}
                        onClick={(e) => e.stopPropagation()}>
              <h2 id="rm-h" className="modal-title">Remove this video?</h2>
              <p className="modal-subject" title={removing.name}>{removing.name}</p>
              <p className="muted body-sm">It's deleted from your Library. Projects already made from it can no longer be exported.</p>
              <div className="modal-actions">
                <button className="btn btn-quiet" onClick={() => setRemoving(null)} autoFocus>Cancel</button>
                <button className="btn btn-danger" onClick={() => { const v = removing; setRemoving(null); removeVideo(v.id).then(() => toast.success(`Removed “${v.name}”.`)).catch((e) => toast.error(`Couldn't remove “${v.name}”: ${e.message}`)); }}>Remove</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {preview && (
          <motion.div className="modal-bg" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                      onClick={() => setPreview(null)}>
            <motion.div className="pv" role="dialog" aria-modal="true" aria-label={`Preview ${preview.name}`}
                        initial={{ scale: 0.97, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.97, opacity: 0 }}
                        onClick={(e) => e.stopPropagation()}>
              <div className="pv-head">
                <span className="pv-title" title={preview.name}>{preview.name}</span>
                <button className="icon-btn" onClick={() => setPreview(null)} aria-label="Close preview" autoFocus>
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
                </button>
              </div>
              {preview.url ? (
                <video className="pv-video" src={preview.url} controls autoPlay playsInline />
              ) : (
                <div className="pv-video pv-loading" role="status"><Loader size={14} /> Preparing the preview…</div>
              )}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
