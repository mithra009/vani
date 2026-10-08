import { motion } from "framer-motion";
import { Check, Dot } from "./Icons.jsx";

export const TRANSCRIBE_STAGES = [
  { key: "ingest", name: "Preparing video", sub: "Checking the file and extracting audio" },
  { key: "transcribe", name: "Transcribing speech", sub: "Gnani Prisma v2.5 finds every line and its timing" },
  { key: "emotion", name: "Reading emotion", sub: "How each line sounds and what it says" },
];

const ALL_DUB_STAGES = {
  clean: { key: "clean", name: "Cleaning your recording", sub: "Noise reduced and loudness evened out" },
  translate: { key: "translate", name: "Translating", sub: "Each line written to fit its time slot" },
  synthesize: { key: "synthesize", name: "Generating voice", sub: "Gnani Timbre v2.5 speaks each line with its emotion" },
  fit: { key: "fit", name: "Fitting to timing", sub: "Every line adjusted to start and end on time" },
  assemble: { key: "assemble", name: "Building the soundtrack", sub: "Lines placed at their original timestamps" },
  mux: { key: "mux", name: "Finishing video", sub: "Mixing with the original audio" },
};

/** Which stages run depends on the voice: your own recording skips translation and synthesis,
 *  and a same-language re-voice skips translation. */
export function dubStages(job) {
  if (job.voice?.mode === "own") return ["clean", "assemble", "mux"].map((k) => ALL_DUB_STAGES[k]);
  const keys = ["translate", "synthesize", "fit", "assemble", "mux"];
  return (job.tgt_lang === job.src_lang ? keys.slice(1) : keys).map((k) => ALL_DUB_STAGES[k]);
}

export default function StageProgress({ title, lead, stages, job }) {
  const current = stages.findIndex((s) => s.key === job.stage);
  const total = stages.length;
  const overall = current < 0 ? 0 : (current + (job.stage_progress || 0)) / total;

  return (
    <div className="progress-wrap page">
      <motion.h1 className="title" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>{title}</motion.h1>
      <p className="lead" style={{ marginTop: 12 }}>{lead}</p>
      <div className="bar" style={{ marginTop: 32, height: 4 }} role="progressbar"
           aria-valuenow={Math.round(overall * 100)} aria-valuemin={0} aria-valuemax={100}>
        <span style={{ width: `${overall * 100}%` }} />
      </div>
      <ol className="stage-list">
        {stages.map((s, i) => {
          const state = i < current ? "done" : i === current ? "active" : "pending";
          return (
            <li key={s.key} className={`stage ${state}`}>
              <span className="stage-icon">
                {state === "done" ? <Check /> : state === "active" ? <span className="spinner" /> : <Dot />}
              </span>
              <span>
                <span className="stage-name">{s.name}</span>
                <span className="stage-sub" style={{ display: "block" }}>{s.sub}</span>
              </span>
              <span className="stage-pct mono">
                {state === "active" ? `${Math.round((job.stage_progress || 0) * 100)}%` : ""}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
