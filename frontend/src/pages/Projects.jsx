import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "../lib/api.js";
import { langName } from "../lib/catalog.js";
import { ago, clock } from "../lib/format.js";

const STATUS = {
  awaiting_narration: { text: "Waiting for narration", cls: "review" },
  transcribing: { text: "Transcribing", cls: "working" },
  review: { text: "Ready to review", cls: "review" },
  dubbing: { text: "Dubbing", cls: "working" },
  done: { text: "Done", cls: "done" },
  failed: { text: "Failed", cls: "failed" },
};

const FILTERS = [["all", "All"], ["working", "In progress"], ["done", "Done"]];

function langs(j) {
  if (j.tgt_lang === "same" || j.tgt_lang === j.src_lang) return langName(j.src_lang);
  return `${j.src_lang === "auto" ? "Auto" : langName(j.src_lang)} to ${langName(j.tgt_lang)}`;
}

function RowMenu({ onRename, onDelete }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  return (
    <div className="user-menu pj-menu" ref={ref}>
      <button className="row-more" aria-label="Project actions" aria-haspopup="menu" aria-expanded={open}
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen((o) => !o); }}>•••</button>
      {open && (
        <div className="menu" role="menu" style={{ minWidth: 170 }}>
          <button className="menu-item" role="menuitem" onClick={(e) => { e.stopPropagation(); setOpen(false); onRename(); }}>Rename</button>
          <button className="menu-item menu-danger" role="menuitem" onClick={(e) => { e.stopPropagation(); setOpen(false); onDelete(); }}>Delete</button>
        </div>
      )}
    </div>
  );
}

export default function Projects() {
  const nav = useNavigate();
  const [jobs, setJobs] = useState(null);
  const [error, setError] = useState(null);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [renaming, setRenaming] = useState(null);     // { id, name }
  const [deleting, setDeleting] = useState(null);     // job
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.listJobs().then(setJobs).catch((e) => setError(e.message));
  }, []);

  const shown = useMemo(() => {
    let xs = jobs || [];
    if (filter === "done") xs = xs.filter((j) => j.status === "done");
    if (filter === "working") xs = xs.filter((j) => j.status !== "done" && j.status !== "failed");
    const s = q.trim().toLowerCase();
    return s ? xs.filter((j) => j.name.toLowerCase().includes(s)) : xs;
  }, [jobs, q, filter]);

  async function saveName() {
    const name = renaming.name.trim();
    if (!name) return;
    setBusy(true);
    try {
      await api.renameJob(renaming.id, name);
      setJobs((js) => js.map((j) => (j.id === renaming.id ? { ...j, name } : j)));
      setRenaming(null);
      setError(null);
    } catch (e) { setError(`Couldn't rename: ${e.message}`); } finally { setBusy(false); }
  }

  async function confirmDelete() {
    setBusy(true);
    try {
      await api.deleteJob(deleting.id);
      setJobs((js) => js.filter((j) => j.id !== deleting.id));
      setDeleting(null);
      setError(null);
    } catch (e) { setError(`Couldn't delete: ${e.message}`); setDeleting(null); } finally { setBusy(false); }
  }

  return (
    <div className="page-wide proj-page">
      <div className="pj-head">
        <h1 className="title">Projects</h1>
        {jobs && <span className="pj-count">{jobs.length}</span>}
      </div>

      <div className="pj-bar">
        <div className="seg-control" role="group" aria-label="Filter projects">
          {FILTERS.map(([k, label]) => (
            <button key={k} aria-pressed={filter === k} onClick={() => setFilter(k)}>{label}</button>
          ))}
        </div>
        <div className="pj-bar-right">
          <input className="input search" type="search" placeholder="Search projects" value={q}
                 onChange={(e) => setQ(e.target.value)} aria-label="Search projects" />
          <Link to="/new" className="btn btn-primary btn-sm pj-new">New project</Link>
        </div>
      </div>

      {error && <div className="banner error" role="alert" style={{ marginBottom: 16 }}><span className="banner-dot" /><span>{error}</span></div>}

      {!jobs && !error && <div className="pj-list"><div className="pj-skel" /><div className="pj-skel" /></div>}

      {jobs && jobs.length === 0 && (
        <div className="pj-empty">
          <p className="pj-empty-title">No projects yet</p>
          <p className="muted body-sm">Dub a video or narrate one yourself. Your projects will appear here.</p>
          <Link to="/new" className="btn btn-primary btn-sm pj-new">New project</Link>
        </div>
      )}

      {jobs && jobs.length > 0 && (
        <ul className="pj-list" aria-label="Projects">
          <AnimatePresence initial={false}>
            {shown.map((j) => {
              const st = STATUS[j.status] || { text: j.status, cls: "" };
              const editing = renaming?.id === j.id;
              const narr = j.mode === "narrate";
              return (
                <motion.li key={j.id} className="pj-row" layout="position"
                           exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
                  <span className={`pj-icon ${narr ? "pj-icon-narr" : ""}`} aria-hidden="true">
                    {narr ? (
                      <svg viewBox="0 0 24 24" width="18" height="18"><rect x="9" y="3.5" width="6" height="11" rx="3" fill="none" stroke="currentColor" strokeWidth="1.7" /><path d="M6 11a6 6 0 0 0 12 0M12 17v3.5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" /></svg>
                    ) : (
                      <svg viewBox="0 0 24 24" width="18" height="18"><path d="M4 9v6M8 6.5v11M12 4v16M16 7.5v9M20 10.5v3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
                    )}
                  </span>

                  {editing ? (
                    <form className="pj-rename" onSubmit={(e) => { e.preventDefault(); saveName(); }}>
                      <input className="input rename-input" autoFocus value={renaming.name} maxLength={120}
                             onChange={(e) => setRenaming({ ...renaming, name: e.target.value })}
                             onKeyDown={(e) => e.key === "Escape" && setRenaming(null)} aria-label="Project name" />
                      <button className="btn btn-primary btn-sm" disabled={busy}>Save</button>
                      <button type="button" className="link-btn body-sm" onClick={() => setRenaming(null)}>Cancel</button>
                    </form>
                  ) : (
                    <Link to={`/jobs/${j.id}`} className="pj-main">
                      <span className="pj-name">{j.name}</span>
                      <span className="pj-meta">
                        {narr ? "Narration" : "Dub"}<span className="pj-sep" aria-hidden="true" />{langs(j)}
                        <span className="pj-sep" aria-hidden="true" /><span className="mono">{clock(j.duration_s)}</span>
                      </span>
                    </Link>
                  )}

                  {!editing && <span className={`pj-status pj-${st.cls}`}>{st.text}</span>}
                  {!editing && <span className="pj-when">{ago(j.created_at)}</span>}
                  {!editing && <RowMenu onRename={() => setRenaming({ id: j.id, name: j.name })} onDelete={() => setDeleting(j)} />}
                </motion.li>
              );
            })}
          </AnimatePresence>
          {shown.length === 0 && <li className="pj-none muted body-sm">No projects match.</li>}
        </ul>
      )}

      <AnimatePresence>
        {deleting && (
          <motion.div className="modal-bg" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                      onClick={() => !busy && setDeleting(null)}>
            <motion.div className="modal" role="alertdialog" aria-modal="true" aria-labelledby="del-h" aria-describedby="del-d"
                        initial={{ scale: 0.96, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.96, opacity: 0 }}
                        onClick={(e) => e.stopPropagation()}>
              <h2 id="del-h" className="modal-title">Delete “{deleting.name}”?</h2>
              <p id="del-d" className="muted body-sm">The project, its transcript and its dubbed video will be removed. This can't be undone.</p>
              <div className="modal-actions">
                <button className="btn btn-quiet" onClick={() => setDeleting(null)} disabled={busy} autoFocus>Cancel</button>
                <button className="btn btn-danger" onClick={confirmDelete} disabled={busy}>{busy ? "Deleting…" : "Delete project"}</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
