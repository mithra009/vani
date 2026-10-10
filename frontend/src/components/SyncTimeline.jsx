import { motion, useReducedMotion } from "framer-motion";

// Original speech (Hindi) and the dub (Tamil): every Vani clip starts exactly where its
// original clip starts, even when the translation runs a little longer or shorter.
const ORIGINAL = [[2, 17], [21, 39], [44, 58], [63, 86], [90, 98]];
const DUB = [[2, 18.5], [21, 37], [44, 59], [63, 84], [90, 98]];
const WAVE = Array.from({ length: 44 }, (_, i) => 0.25 + 0.75 * Math.abs(Math.sin(i * 1.7) * Math.cos(i * 0.6)));

function Track({ label, lang, clips, tone, delay }) {
  return (
    <div className="st-track">
      <div className="st-label">
        <span>{label}</span>
        <span className="st-lang">{lang}</span>
      </div>
      <div className="st-lane">
        {clips.map(([a, b], i) => (
          <motion.span
            key={i}
            className={`st-clip st-${tone}`}
            style={{ left: `${a}%`, width: `${b - a}%` }}
            initial={{ opacity: 0, scaleX: 0.6 }}
            animate={{ opacity: 1, scaleX: 1 }}
            transition={{ delay: delay + i * 0.08, duration: 0.5, ease: [0.28, 0.11, 0.32, 1] }}
          >
            <span className="st-wave" aria-hidden="true">
              {WAVE.slice(0, Math.max(6, Math.round((b - a) * 1.6))).map((h, k) => (
                <i key={k} style={{ height: `${h * 100}%` }} />
              ))}
            </span>
          </motion.span>
        ))}
      </div>
    </div>
  );
}

export default function SyncTimeline() {
  const reduce = useReducedMotion();
  return (
    <figure className="sync-tl" aria-label="Illustration: dubbed clips start exactly where the original lines start">
      <div className="st-ruler" aria-hidden="true">
        {["0:00", "0:15", "0:30", "0:45", "1:00"].map((t) => <span key={t}>{t}</span>)}
      </div>
      <div className="st-body">
        <Track label="Original" lang="हिन्दी" clips={ORIGINAL} tone="orig" delay={0.3} />
        <Track label="Vani" lang="தமிழ்" clips={DUB} tone="dub" delay={0.6} />
        <div className="st-overlay" aria-hidden="true">
          {ORIGINAL.map(([a]) => <span key={a} className="st-guide" style={{ left: `${a}%` }} />)}
          {!reduce && (
            <motion.span className="st-playhead"
                         initial={{ left: "0%" }} animate={{ left: "100%" }}
                         transition={{ duration: 9, ease: "linear", repeat: Infinity, repeatDelay: 0.6 }} />
          )}
        </div>
      </div>
      <figcaption className="st-cap">Every dubbed line starts on the frame its original did. No drift, start to finish.</figcaption>
    </figure>
  );
}
