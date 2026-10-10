import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api.js";
import { langName } from "../lib/catalog.js";
import StageProgress, { dubStages, TRANSCRIBE_STAGES } from "../components/StageProgress.jsx";
import Narrate from "../components/Narrate.jsx";
import Review from "../components/Review.jsx";
import VoiceStep from "../components/VoiceStep.jsx";
import Result from "../components/Result.jsx";

const DUB_STEPS = ["Transcribe", "Review", "Voice", "Dub", "Done"];
const NARRATE_STEPS = ["Record", "Transcribe", "Review", "Voice", "Done"];

function stepIndex(job, sub) {
  const narrate = job.mode === "narrate";
  const base = narrate ? 1 : 0;
  if (job.status === "awaiting_narration") return 0;
  if (job.status === "transcribing") return base;
  if (job.status === "review") return base + (sub === "voice" ? 2 : 1);
  if (job.status === "dubbing") return narrate ? 3 : 3;
  return 4;
}

export default function Job({ mode }) {
  const { id } = useParams();
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const [sub, setSub] = useState("review");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let off = () => {};
    api.getJob(id)
      .then((j) => { setJob(j); off = api.subscribe(id, setJob); })
      .catch((e) => setError(e.message));
    return () => off();
  }, [id]);

  useEffect(() => { window.scrollTo({ top: 0 }); }, [job?.status, sub]);

  if (error) {
    return (
      <div className="page empty">
        <p className="subhead">Couldn't open this project</p>
        <p className="muted">{error}</p>
        <Link to="/projects">Back to projects</Link>
      </div>
    );
  }
  if (!job) return <div className="progress-wrap"><div className="spinner" style={{ margin: "0 auto" }} /></div>;

  async function run(fn) {
    setBusy(true);
    try { await fn(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  const submitNarration = (take) => run(async () => setJob(await api.uploadNarration(job.id, take)));
  const toVoice = (segments) => run(async () => { setJob(await api.updateSegments(job.id, segments)); setSub("voice"); });
  const startDub = (settings) => run(async () => setJob(await api.startDub(job.id, settings)));

  const narrate = job.mode === "narrate";
  const steps = narrate ? NARRATE_STEPS : DUB_STEPS;
  const current = stepIndex(job, sub);

  return (
    <>
      <div className="page-wide job-head">
        <div style={{ minWidth: 0 }}>
          <p className="body-sm dim">
            {narrate ? "Narration" : ""}
            {job.src_lang !== "auto" && `${narrate ? ", " : ""}${langName(job.src_lang)}`}
            {job.tgt_lang !== "same" && job.tgt_lang !== job.src_lang && `${narrate || job.src_lang !== "auto" ? " to " : "To "}${langName(job.tgt_lang)}`}
          </p>
          <h1 className="title" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{job.name}</h1>
        </div>
        <nav aria-label="Progress">
          <ol className="steps">
            {steps.map((s, i) => (
              <li key={s} className={i === current ? "on" : i < current ? "done" : ""} aria-current={i === current ? "step" : undefined}>
                {s}{i < steps.length - 1 && <span className="sep" aria-hidden="true">›</span>}
              </li>
            ))}
          </ol>
        </nav>
      </div>

      {job.status === "awaiting_narration" && <Narrate job={job} onSubmit={submitNarration} submitting={busy} />}

      {job.status === "transcribing" && (
        <StageProgress
          title={narrate ? "Transcribing your narration" : "Listening to your video"}
          lead={narrate ? "Every line you said is found and timed to the video." : "This takes about a minute for every few minutes of video."}
          stages={TRANSCRIBE_STAGES} job={job} />
      )}

      {job.status === "review" && sub === "review" && <Review job={job} onContinue={toVoice} saving={busy} />}

      {job.status === "review" && sub === "voice" && (
        <VoiceStep job={job} mode={mode} onBack={() => setSub("review")} onStart={startDub} starting={busy} />
      )}

      {job.status === "dubbing" && (
        <StageProgress
          title={job.voice?.mode === "own" ? "Adding your narration"
            : narrate && job.tgt_lang === job.src_lang ? "Re-voicing your narration"
            : `Dubbing into ${langName(job.tgt_lang)}`}
          lead="You can leave this page. The project keeps going and appears in Projects."
          stages={dubStages(job)} job={job} />
      )}

      {job.status === "done" && <Result job={job} onJob={setJob} />}

      {job.status === "failed" && (
        <div className="page empty">
          <p className="subhead">Processing stopped</p>
          <p className="muted">{job.error || "Something went wrong while processing this video."}</p>
          <Link to="/new">Try another video</Link>
        </div>
      )}
    </>
  );
}
