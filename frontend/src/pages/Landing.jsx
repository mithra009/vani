import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { langName } from "../lib/catalog.js";
import { refreshLibrary, useLibrary } from "../lib/libraryStore.js";
import { ago } from "../lib/format.js";
import SyncTimeline from "../components/SyncTimeline.jsx";
import { Arrow } from "../components/Icons.jsx";

const reveal = {
  initial: { opacity: 0, y: 24 },
  whileInView: { opacity: 1, y: 0 },
  viewport: { once: true, margin: "-80px" },
  transition: { duration: 0.7, ease: [0.28, 0.11, 0.32, 1] },
};

const STATUS = {
  awaiting_narration: "Waiting for narration", transcribing: "Transcribing", review: "Ready to review",
  dubbing: "Dubbing", done: "Done", failed: "Failed",
};

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

const FEATURES = [
  {
    k: "dub", title: "Dub any video",
    body: "Speech is transcribed, translated to fit each line's time, and spoken again in one of ten Indian languages or Hinglish.",
  },
  {
    k: "narrate", title: "Narrate it yourself",
    body: "Record over your video as it plays. Keep your own voice, or have your words re-voiced and translated.",
  },
  {
    k: "emotion", title: "Emotion that carries over",
    body: "A laugh stays a laugh, a whisper stays a whisper. Each line's feeling is read from the original and performed again.",
  },
  {
    k: "clone", title: "Your own voice, in any language",
    body: "With consent, five seconds of a voice is enough to dub in it. Every cloned voice is labelled as AI-generated.",
  },
  {
    k: "sync", title: "Sample-accurate sync",
    body: "Lines are placed on the timeline by their original timecode and fitted to their slot, so nothing drifts.",
  },
];

const MODELS = [
  { name: "Prisma v2.5", role: "Speech to text", body: "Finds every spoken line and its exact timing, trained on over 14 million hours of Indian telephone audio. Handles Hinglish and other code-mixed speech." },
  { name: "Timbre v2.5", role: "Text to speech", body: "42 natural voices across ten Indian languages, with audio tags for laughter, whispers and sighs, and correct reading of lakh and crore." },
  { name: "Voice cloning", role: "Text to speech", body: "Builds a voice from 5 to 30 seconds of clean speech, so a creator can be heard in languages they don't speak." },
];

const TEAM = [
  { name: "Mithravardhan P N", photo: "/team/mithra.jpg", linkedin: "https://www.linkedin.com/in/mithravardhanpn/",
    github: "https://github.com/mithra009", email: "mithravardhanpn@gmail.com" },
  { name: "Arko Bera", photo: "/team/arko.jpg", linkedin: "https://www.linkedin.com/in/arko-bera-682599239/",
    github: "https://github.com/arkobera", email: "arkobera77@gmail.com" },
];

const SOCIAL = {
  linkedin: ["LinkedIn", <path key="l" fill="currentColor" d="M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zM7.12 20.45H3.56V9h3.56v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z" />],
  github: ["GitHub", <path key="g" fill="currentColor" d="M12 .3a12 12 0 0 0-3.8 23.38c.6.12.83-.26.83-.57v-2c-3.34.73-4.04-1.6-4.04-1.6-.55-1.4-1.34-1.77-1.34-1.77-1.08-.74.09-.73.09-.73 1.2.09 1.83 1.24 1.83 1.24 1.07 1.83 2.8 1.3 3.49 1 .1-.78.42-1.3.76-1.6-2.67-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.14-.3-.54-1.52.1-3.18 0 0 1-.32 3.3 1.23a11.5 11.5 0 0 1 6 0c2.28-1.55 3.29-1.23 3.29-1.23.64 1.66.24 2.88.12 3.18a4.65 4.65 0 0 1 1.23 3.22c0 4.61-2.8 5.63-5.48 5.92.42.36.81 1.1.81 2.22v3.29c0 .32.21.7.82.58A12 12 0 0 0 12 .3z" />],
  email: ["Email", <path key="e" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" d="M3 5.5h18v13H3zM3.5 6l8.5 7 8.5-7" />],
};

export default function Landing({ mode }) {
  const library = useLibrary();
  useEffect(() => { refreshLibrary(); }, []);
  const { profile } = useAuth() || {};
  const [projects, setProjects] = useState(null);

  useEffect(() => {
    api.listJobs().then(setProjects).catch(() => setProjects([]));
  }, []);

  const first = profile?.first_name;
  const recent = (projects || []).slice(0, 3);

  return (
    <div className="landing">
      {/* ---------- hero ---------- */}
      <section className="l-hero">
        <motion.p className="l-eyebrow" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.6 }}>
          {first ? `${greeting()}, ${first}.` : "Welcome to Vani."}
        </motion.p>
        <motion.h1 className="l-headline" initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }}
                   transition={{ duration: 0.8, ease: [0.28, 0.11, 0.32, 1] }}>
          Every voice.<br />Every Indian language.
        </motion.h1>
        <motion.p className="l-lead" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15, duration: 0.7 }}>
          Vani dubs your videos into ten Indian languages and Hinglish, keeps each line on time,
          and carries the feeling of the original voice across.
        </motion.p>
        <motion.div className="l-ctas" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3, duration: 0.6 }}>
          <Link to="/new" className="btn btn-primary">Start a new project</Link>
          <Link to="/projects" className="l-link">Open your projects <span aria-hidden="true">›</span></Link>
        </motion.div>
        <motion.div className="l-visual" initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.35, duration: 0.9, ease: [0.28, 0.11, 0.32, 1] }}>
          <SyncTimeline />
        </motion.div>
      </section>

      {/* ---------- workspace ---------- */}
      <section className="l-section">
        <motion.div className="l-section-head" {...reveal}>
          <h2 className="l-h2">Your workspace</h2>
        </motion.div>
        <div className="ws-grid">
          <motion.div {...reveal}>
            <Link to="/projects" className="ws-card ws-projects">
              <div className="ws-top">
                <span className="ws-kicker">Projects</span>
                <span className="ws-count">{projects ? projects.length : "–"}</span>
              </div>
              {recent.length > 0 ? (
                <ul className="ws-recent">
                  {recent.map((p) => (
                    <li key={p.id}>
                      <span className="ws-name">{p.name}</span>
                      <span className="ws-meta">{STATUS[p.status] || p.status}, {ago(p.created_at)}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="ws-empty">{projects ? "No projects yet. Your dubs and narrations will appear here." : "Loading…"}</p>
              )}
              <span className="ws-go">View all projects <Arrow /></span>
            </Link>
          </motion.div>
          <motion.div {...reveal} transition={{ ...reveal.transition, delay: 0.08 }}>
            <Link to="/library" className="ws-card ws-library">
              <div className="ws-top">
                <span className="ws-kicker">Library</span>
                <span className="ws-count">{library.length}</span>
              </div>
              <div className="ws-thumbs" aria-hidden="true">
                {library.slice(0, 4).map((v) => <span key={v.id} style={{ background: v.cover || "var(--surface-3)" }} />)}
              </div>
              <span className="ws-go">Open library <Arrow /></span>
            </Link>
          </motion.div>
          <motion.div {...reveal} transition={{ ...reveal.transition, delay: 0.16 }}>
            <Link to="/new" className="ws-card ws-new">
              <span className="ws-plus" aria-hidden="true">+</span>
              <span className="ws-new-title">New project</span>
              <span className="ws-meta">Dub a video or narrate one yourself</span>
            </Link>
          </motion.div>
        </div>
      </section>

      {/* ---------- features ---------- */}
      <section className="l-section">
        <motion.div className="l-section-head" {...reveal}>
          <h2 className="l-h2">One video. Every audience.</h2>
          <p className="l-sub">Most of India watches in a language other than the one a video was made in. Vani closes that gap without a studio.</p>
        </motion.div>
        <div className="bento">
          {FEATURES.map((f, i) => (
            <motion.article key={f.k} className={`bento-tile bento-${f.k}`} {...reveal}
                            transition={{ ...reveal.transition, delay: (i % 3) * 0.08 }}>
              <h3>{f.title}</h3>
              <p>{f.body}</p>
            </motion.article>
          ))}
        </div>
      </section>

      {/* ---------- gnani ---------- */}
      <section className="l-section l-gnani">
        <motion.div className="l-section-head" {...reveal}>
          <p className="l-kicker">Powered by Gnani.ai</p>
          <h2 className="l-h2">Built on speech models made for India.</h2>
          <p className="l-sub">
            Gnani builds voice AI trained on Indian speech, accents and code-mixing. Vani uses its models for every word it hears and speaks.
          </p>
        </motion.div>
        <motion.dl className="l-stats" {...reveal}>
          <div><dt>Languages</dt><dd>10 <small>+ Hinglish</small></dd></div>
          <div><dt>Voices</dt><dd>42</dd></div>
          <div><dt>To clone a voice</dt><dd>5 s</dd></div>
          <div><dt>Longest video</dt><dd>10 min</dd></div>
        </motion.dl>
        <div className="model-grid">
          {MODELS.map((m, i) => (
            <motion.article key={m.name} className="model-card" {...reveal} transition={{ ...reveal.transition, delay: i * 0.08 }}>
              <span className="model-role">{m.role}</span>
              <h3>{m.name}</h3>
              <p>{m.body}</p>
            </motion.article>
          ))}
        </div>
        <motion.p className="l-note" {...reveal}>Translation and emotion reading currently use Google Gemini 3.5 Flash-Lite.</motion.p>
      </section>

      {/* ---------- team ---------- */}
      <section className="l-section l-team">
        <motion.div className="l-section-head" {...reveal}>
          <h2 className="l-h2">The team</h2>
        </motion.div>
        <div className="team-grid">
          {TEAM.map((t, i) => (
            <motion.div key={t.name} className="team-card" {...reveal} transition={{ ...reveal.transition, delay: i * 0.1 }}>
              <img className="team-avatar" src={t.photo} alt={t.name} width="64" height="64" loading="lazy" />
              <span className="team-name">{t.name}</span>
              <span className="team-role">Developer</span>
              <div className="team-links">
                {["linkedin", "github", "email"].map((k) => (
                  // Email opens Gmail's compose window: mailto: does nothing without a desktop mail app.
                  <a key={k} className="team-link" target="_blank" rel="noopener noreferrer"
                     href={k === "email" ? `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(t[k])}` : t[k]}
                     aria-label={`${t.name} on ${SOCIAL[k][0]}`} title={SOCIAL[k][0]}>
                    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">{SOCIAL[k][1]}</svg>
                  </a>
                ))}
              </div>
            </motion.div>
          ))}
        </div>
      </section>

      {mode === "demo" && (
        <p className="caption" style={{ textAlign: "center", paddingBottom: 24 }}>Demo mode: the backend isn't running, so projects are simulated.</p>
      )}
    </div>
  );
}
