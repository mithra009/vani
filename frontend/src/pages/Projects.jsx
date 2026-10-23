import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "../lib/api.js";
import * as editorApi from "../lib/editorApi.js";
import { langName } from "../lib/catalog.js";
import { ago, clock } from "../lib/format.js";
import { toast } from "../lib/toast.jsx";

// One list for every project, whichever service holds it. A row only needs:
// { key, id, source, kind, name, status, bucket, href, langs, duration_s, created_at }.
// bucket drives the filters: working (in progress) | ready | failed.

const DUB_STATUS = {
  awaiting_narration: ["Waiting for narration", "working"],
  transcribing: ["Transcribing", "working"],
  review: ["Ready to review", "ready"],
  dubbing: ["Dubbing", "working"],
  done: ["Done", "ready"],
  failed: ["Failed", "failed"],
};
const EDITOR_STATUS = {
  draft: ["Draft", "working"],
  awaiting_narration: ["Waiting for narration", "working"],
  generating: ["Generating voice", "working"],
  editing: ["Ready to edit", "ready"],
  failed: ["Failed", "failed"],
};
const KIND_LABEL = { video_audio: "Dub", script: "Script", narration: "Narration", dub: "Dub", narrate: "Narration" };
const FILTERS = [["all", "All"], ["working", "In progress"], ["ready", "Done"]];

function langs(src, tgt) {
  if (!tgt || tgt === "same" || tgt === src) return langName(src);
  return `${src === "auto" ? "Auto" : langName(src)} → ${langName(tgt)}`;
}

function fromJob(j) {
  const [text, bucket] = DUB_STATUS[j.status] || [j.status, "working"];
  return {
    key: `job:${j.id}`, id: j.id, source: "job", kind: j.mode === "narrate" ? "narrate" : "dub", name: j.name,
    status: text, bucket, href: `/jobs/${j.id}`, langs: langs(j.src_lang, j.tgt_lang),
    watch: j.status === "done" ? () => Promise.resolve(api.downloads(j).video) : null,
    duration_s: j.duration_s, created_at: typeof j.created_at === "number" ? j.created_at : Date.parse(j.created_at),
  };
}

function fromEditor(p) {
  const [text, bucket] = EDITOR_STATUS[p.status] || [p.status, "working"];
  return {
    key: `ed:${p.id}`, id: p.id, source: "editor", kind: p.input_kind, name: p.name,
    status: text, bucket, href: `/editor/${p.id}`, langs: langs(p.src_lang, p.tgt_lang),
    watch: p.latest_export_id ? () => editorApi.exportUrl(p.id, p.latest_export_id).then((r) => r.url) : null,
    duration_s: p.duration_s, created_at: Date.parse(p.created_at),
  };
}

const ICONS = {
  narration: <><rect x="9" y="3.5" width="6" height="11" rx="3" /><path d="M6 11a6 6 0 0 0 12 0M12 17v3.5" /></>,
  script: <><path d="M7 4h7l4 4v12H7z" /><path d="M14 4v4h4M10 12h5M10 15.5h5" /></>,
  dub: <path d="M4 9v6M8 6.5v11M12 4v16M16 7.5v9M20 10.5v3" />,
};
const iconFor = (kind) => ICONS[kind === "narrate" ? "narration" : kind === "script" ? "script" : kind === "narration" ? "narration" : "dub"];

function RowMenu({ canRename, onRename, onDelete }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    const esc = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <div className="user-menu pj-menu" ref={ref}>
      <button className="row-more" aria-label="Project actions" aria-haspopup="menu" aria-expanded={open}
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen((o) => !o); }}>•••</button>
      {open && (
        <div className="menu" role="menu" style={{ minWidth: 170 }}>
          {canRename && <button className="menu-item" role="menuitem" onClick={() => { setOpen(false); onRename(); }}>Rename</button>}
          <button className="menu-item menu-danger" role="menuitem" onClick={() => { setOpen(false); onDelete(); }}>Delete</button>
        </div>
      )}
    </div>
  );
}

export default function Projects() {
  const [jobs, setJobs] = useState(null);           // dubbing backend
  const [edits, setEdits] = useState(null);         // editor service
  const [errors, setErrors] = useState([]);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [renaming, setRenaming] = useState(null);   // { id, name }
  const [deleting, setDeleting] = useState(null);   // row
  const [busy, setBusy] = useState(false);
  const [watching, setWatching] = useState(null);   // { name, url }

  async function watch(r) {
    try { setWatching({ name: r.name, url: await r.watch() }); }
    catch (e) { toast.error(`Couldn't open the video: ${e.message}`); }
  }

  useEffect(() => {
    // Each source fails on its own: one service being down never hides the other's projects.
    api.listJobs().then(setJobs).catch((e) => { setJobs([]); setErrors((x) => [...x, `Dubbing projects: ${e.message}`]); });
    editorApi.listProjects().then(setEdits).catch((e) => { setEdits([]); setErrors((x) => [...x, `Editor projects: ${e.message}`]); });
  }, []);

  const loaded = jobs !== null && edits !== null;
  const rows = useMemo(() => {
    if (!loaded) return [];
    return [...edits.map(fromEditor), ...jobs.map(fromJob)].sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
  }, [jobs, edits, loaded]);

  const counts = useMemo(() => ({
    all: rows.length,
    working: rows.filter((r) => r.bucket === "working").length,
    ready: rows.filter((r) => r.bucket === "ready").length,
  }), [rows]);

  const shown = useMemo(() => {
    let xs = filter === "all" ? rows : rows.filter((r) => r.bucket === filter);
    const s = q.trim().toLowerCase();
    if (s) xs = xs.filter((r) => r.name.toLowerCase().includes(s));
    return xs;
  }, [rows, q, filter]);

  async function saveName() {
    const name = renaming.name.trim();
    if (!name) return;
    setBusy(true);
    try {
      await api.renameJob(renaming.id, name);
      setJobs((js) => js.map((j) => (j.id === renaming.id ? { ...j, name } : j)));
      setRenaming(null);
    } catch (e) { toast.error(`Couldn't rename: ${e.message}`); } finally { setBusy(false); }
  }

  async function confirmDelete() {
    setBusy(true);
    try {
      if (deleting.source === "editor") {
        await editorApi.deleteProject(deleting.id);
        setEdits((xs) => xs.filter((x) => x.id !== deleting.id));
      } else {
        await api.deleteJob(deleting.id);
        setJobs((js) => js.filter((j) => j.id !== deleting.id));
      }
      toast.success(`Deleted “${deleting.name}”.`);
      setDeleting(null);
    } catch (e) { toast.error(`Couldn't delete “${deleting.name}”: ${e.message}`); setDeleting(null); } finally { setBusy(false); }
  }

  return (
    <div className="page-wide proj-page">
      <div className="pj-head">
        <h1 className="pg-title">Projects</h1>
        {loaded && <span className="pj-total">{counts.all} {counts.all === 1 ? "project" : "projects"}</span>}
      </div>

      <div className="pj-bar">
        <div className="seg-control" role="group" aria-label="Filter projects">
          {FILTERS.map(([k, label]) => (
            <button key={k} aria-pressed={filter === k} onClick={() => setFilter(k)}>
              {label}{loaded && <span className="seg-n">{counts[k]}</span>}
            </button>
          ))}
        </div>
        <div className="pj-bar-right">
          <input className="input search" type="search" placeholder="Search projects" value={q}
                 onChange={(e) => setQ(e.target.value)} aria-label="Search projects" />
          <Link to="/new" className="btn btn-primary btn-ctl">New project</Link>
        </div>
      </div>

      {errors.map((e, i) => (
        <div key={i} className="banner error" role="alert" style={{ marginBottom: 12 }}><span className="banner-dot" /><span>{e}</span></div>
      ))}

      {!loaded && <div className="pj-list"><div className="pj-skel" /><div className="pj-skel" /></div>}

      {loaded && rows.length === 0 && (
        <div className="pj-empty">
          <p className="pj-empty-title">No projects yet</p>
          <p className="muted body-sm">Pick a video from your Library to dub, script or narrate it.</p>
          <Link to="/new" className="btn btn-primary btn-ctl">New project</Link>
        </div>
      )}

      {loaded && rows.length > 0 && (
        <ul className="pj-list" aria-label="Projects">
          <AnimatePresence initial={false}>
            {shown.map((r) => {
              const editing = renaming?.id === r.id && r.source === "job";
              return (
                <motion.li key={r.key} className="pj-row" layout="position" exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
                  <span className={`pj-icon pj-icon-${r.kind === "narrate" ? "narration" : r.kind}`} aria-hidden="true">
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7"
                         strokeLinecap="round" strokeLinejoin="round">{iconFor(r.kind)}</svg>
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
                    <Link to={r.href} className="pj-main">
                      <span className="pj-name">{r.name}</span>
                      <span className="pj-meta">
                        {KIND_LABEL[r.kind] || "Project"}<span className="pj-sep" aria-hidden="true" />{r.langs}
                        {r.duration_s != null && <><span className="pj-sep" aria-hidden="true" /><span className="mono">{clock(r.duration_s)}</span></>}
                      </span>
                    </Link>
                  )}
                  {/* In Done every row is finished, so the badge says nothing; offer the latest export instead. */}
                  {!editing && filter === "ready"
                    ? (r.watch
                        ? <button className="btn btn-secondary btn-sm pj-watch" onClick={() => watch(r)}>▶ Watch</button>
                        : <span className="pj-watch-none muted body-sm">Not exported yet</span>)
                    : !editing && <span className={`pj-status pj-${r.bucket}`}>{r.status}</span>}
                  {!editing && <span className="pj-when">{r.created_at ? ago(r.created_at) : ""}</span>}
                  {!editing && <RowMenu canRename={r.source === "job"} onRename={() => setRenaming({ id: r.id, name: r.name })}
                                        onDelete={() => setDeleting(r)} />}
                </motion.li>
              );
            })}
          </AnimatePresence>
          {shown.length === 0 && <li className="pj-none muted body-sm">No projects match.</li>}
        </ul>
      )}

      <AnimatePresence>
        {watching && (
          <motion.div className="modal-bg" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                      onClick={() => setWatching(null)}>
            <motion.div className="modal pj-player" role="dialog" aria-modal="true" aria-label={watching.name}
                        initial={{ scale: 0.96, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.96, opacity: 0 }}
                        onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.key === "Escape" && setWatching(null)}>
              <p className="modal-subject" title={watching.name}>{watching.name}</p>
              <video src={watching.url} controls autoPlay playsInline />
              <div className="modal-actions">
                <a className="btn btn-quiet" href={watching.url} download>Download</a>
                <button className="btn btn-primary" onClick={() => setWatching(null)} autoFocus>Close</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {deleting && (
          <motion.div className="modal-bg" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                      onClick={() => !busy && setDeleting(null)}>
            <motion.div className="modal" role="alertdialog" aria-modal="true" aria-labelledby="del-h" aria-describedby="del-d"
                        initial={{ scale: 0.96, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.96, opacity: 0 }}
                        onClick={(e) => e.stopPropagation()}>
              <h2 id="del-h" className="modal-title">Delete this project?</h2>
              <p className="modal-subject" title={deleting.name}>{deleting.name}</p>
              <p id="del-d" className="muted body-sm">
                {deleting.source === "editor"
                  ? "Its chunks, voice audio, timeline and exports will be removed. The video stays in your Library."
                  : "The project, its transcript and its dubbed video will be removed."} This can't be undone.
              </p>
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
