import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
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

export default function Projects() {
  const [jobs, setJobs] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.listJobs().then(setJobs).catch((e) => setError(e.message));
  }, []);

  return (
    <div className="page" style={{ paddingTop: 48, paddingBottom: 80 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, marginBottom: 28 }}>
        <h1 className="title">Projects</h1>
        <Link to="/" className="btn btn-primary btn-sm" style={{ textDecoration: "none" }}>New dub</Link>
      </div>

      {error && <div className="banner error" role="alert"><span className="banner-dot" /><span>{error}</span></div>}

      {jobs && jobs.length === 0 && (
        <div className="empty card">
          <p className="subhead">No projects yet</p>
          <p className="muted">Upload a video to make your first dub.</p>
          <Link to="/" className="btn btn-secondary" style={{ textDecoration: "none" }}>Upload a video</Link>
        </div>
      )}

      {jobs && jobs.length > 0 && (
        <div className="projects">
          {jobs.map((j) => {
            const st = STATUS[j.status] || { text: j.status, cls: "" };
            return (
              <Link key={j.id} to={`/jobs/${j.id}`} className="project">
                <span style={{ minWidth: 0 }}>
                  <span style={{ display: "block", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{j.name}</span>
                  <span className="body-sm dim">{langName(j.src_lang)} to {langName(j.tgt_lang)}, {clock(j.duration_s)}</span>
                </span>
                <span className={`status ${st.cls}`}>{st.text}</span>
                <span className="body-sm dim">{ago(j.created_at)}</span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
