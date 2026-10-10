import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { langName } from "../lib/catalog.js";
import { LIBRARY } from "../lib/library.js";
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
  { name: "Mithravardhan P N", initials: "MP" },
  { name: "Arko Bera", initials: "AB" },
];

export default function Landing({ mode }) {
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
                <span className="ws-count">{LIBRARY.length}</span>
              </div>
              <div className="ws-thumbs" aria-hidden="true">
                {LIBRARY.slice(0, 4).map((v) => <span key={v.id} style={{ background: v.cover }} />)}
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
          <p className="l-sub">Vani is built by two developers for Gnani.ai's Great Indian AI Internship Challenge 2026.</p>
        </motion.div>
        <div className="team-grid">
          {TEAM.map((t, i) => (
            <motion.div key={t.name} className="team-card" {...reveal} transition={{ ...reveal.transition, delay: i * 0.1 }}>
              <span className="team-avatar" aria-hidden="true">{t.initials}</span>
              <span className="team-name">{t.name}</span>
              <span className="team-role">Developer</span>
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
