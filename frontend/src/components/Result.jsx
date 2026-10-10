import { useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Link } from "react-router-dom";
import Player from "./Player.jsx";
import { api } from "../lib/api.js";
import { EMOTIONS, langName } from "../lib/catalog.js";
import { tc } from "../lib/format.js";
import { Download } from "./Icons.jsx";

const stripTags = (t) => (t || "").replace(/<[^>]+>\s*/g, "");
const tagsOf = (t) => [...(t || "").matchAll(/<([^>]+)>/g)].map((m) => m[1]);

export default function Result({ job, onJob }) {
  const [view, setView] = useState("dub");
  const [busyIdx, setBusyIdx] = useState(null);
  const [active, setActive] = useState(null);
  const player = useRef(null);
  const links = useMemo(() => api.downloads(job), [job]);
  const flagged = job.segments.filter((s) => s.flags?.length);
  const s = job.stats || {};

  async function regen(idx) {
    setBusyIdx(idx);
    try { onJob(await api.regenerate(job.id, idx)); } finally { setBusyIdx(null); }
  }

  const onTime = (t) => {
    const cur = job.segments.find((x) => t >= x.start_s && t <= x.end_s);
    if (cur && cur.idx !== active) setActive(cur.idx);
  };

  return (
    <div className="page-wide">
      <section className="result-hero">
        <motion.h1 className="title" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
          {job.voice?.mode === "own" ? "Your narration is in." : `Your video is ready in ${langName(job.tgt_lang)}.`}
        </motion.h1>
        <p className="lead" style={{ marginTop: 10 }}>
          {job.voice?.mode === "own"
            ? `${s.segments} lines, placed exactly where you said them, with ${langName(job.tgt_lang)} subtitles.`
            : `${s.segments} lines ${job.mode === "narrate" ? "voiced" : "dubbed"}${job.voice?.mode === "clone" ? (job.voice.source === "video" ? ` in a clone of ${job.mode === "narrate" ? "your" : "the speaker's"} voice` : " in your cloned voice") : job.voice?.voice_id ? ` by ${job.voice.voice_id}` : ""}, each starting exactly on time.`}
        </p>
        {job.demo && (
          <p className="caption" style={{ marginTop: 10 }}>Demo mode: the video below is your original, undubbed. The translations shown are sample text.</p>
        )}
      </section>

      <div className="result">
        <div className="stack" style={{ gap: 22 }}>
          <div>
            <Player ref={player} key={view} src={view === "dub" ? job.output_url : job.video_url}
                    segments={job.segments} activeIdx={active} onTime={onTime}
                    captionKey={view === "dub" ? "tgt_text" : "src_text"}
                    label={view === "dub" ? `Dubbed video, ${langName(job.tgt_lang)}` : "Original video"} />
            <div className="ab">
              <div className="seg-control" role="group" aria-label="Compare">
                <button aria-pressed={view === "dub"} onClick={() => setView("dub")}>Dubbed</button>
                <button aria-pressed={view === "orig"} onClick={() => setView("orig")}>Original</button>
              </div>
            </div>
          </div>

          <section aria-labelledby="tr-h">
            <h2 id="tr-h" className="subhead" style={{ fontSize: 24, marginBottom: 14 }}>Line by line</h2>
            <div className="seg-list">
              {job.segments.map((x) => (
                <div key={x.idx} className={`seg ${x.idx === active ? "active" : ""} ${x.flags?.length ? "flagged" : ""}`}>
                  <div className="seg-time mono">
                    <button onClick={() => player.current?.playRange(x.start_s, x.end_s)} title="Play this line">{tc(x.start_s)}</button>
                  </div>
                  <div className="seg-body">
                    <p>{stripTags(x.tgt_text)}</p>
                    <p className="seg-tgt body-sm">{x.src_text}</p>
                    <div className="seg-tools">
                      <span className={`tag emo-${x.emotion}`} style={{ color: "var(--emo)" }}>{EMOTIONS[x.emotion]?.label}</span>
                      {tagsOf(x.tgt_text).map((t) => <span key={t} className="tag">{t}</span>)}
                      {x.stretch && x.stretch > 1.005 && <span className="tag mono">{x.stretch.toFixed(2)}× pace</span>}
                      {x.keep_original && <span className="tag">Original audio kept</span>}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>

        <aside className="side-card">
          <div className="downloads">
            <a className="dl" href={links.video} download={`${job.name.replace(/\.[^.]+$/, "")}.${job.tgt_lang}.mp4`}>
              <span><span style={{ display: "block" }}>Dubbed video</span><small>MP4</small></span><Download />
            </a>
            <a className="dl" href={links.srtTarget} download={`${job.name.replace(/\.[^.]+$/, "")}.${job.tgt_lang}.srt`}>
              <span><span style={{ display: "block" }}>{langName(job.tgt_lang)} subtitles</span><small>SRT</small></span><Download />
            </a>
            <a className="dl" href={links.srtSource} download={`${job.name.replace(/\.[^.]+$/, "")}.${job.src_lang}.srt`}>
              <span><span style={{ display: "block" }}>{langName(job.src_lang)} subtitles</span><small>SRT</small></span><Download />
            </a>
          </div>

          <div className="stat-grid" aria-label="Timing report">
            <div className="stat"><div className="stat-v mono">{s.segments ?? "–"}</div><div className="stat-k">Lines placed on time</div></div>
            <div className="stat"><div className="stat-v mono" style={{ color: s.flagged ? "var(--orange)" : undefined }}>{s.flagged ?? "–"}</div><div className="stat-k">Need a look</div></div>
            <div className="stat"><div className="stat-v mono">{s.stretch_p95 ? `${s.stretch_p95.toFixed(2)}×` : "–"}</div><div className="stat-k">Fastest pace (95th pct)</div></div>
            <div className="stat"><div className="stat-v mono">{s.duration_error_samples ?? "–"}</div><div className="stat-k">Samples of length drift</div></div>
          </div>

          {flagged.length > 0 && (
            <div className="card card-pad stack" style={{ gap: 14 }}>
              <h3 style={{ fontSize: 17, fontWeight: 600 }}>Lines that needed speeding up</h3>
              {flagged.map((x) => (
                <div key={x.idx} className="stack" style={{ gap: 8 }}>
                  <p className="body-sm">
                    <span className="mono dim">{tc(x.start_s)}</span>{"  "}{stripTags(x.tgt_text).slice(0, 80)}{stripTags(x.tgt_text).length > 80 ? "…" : ""}
                  </p>
                  <p className="caption">Played at {x.stretch?.toFixed(2)}× to fit. Regenerating tries a shorter translation.</p>
                  <button className="btn btn-quiet btn-sm" style={{ width: "fit-content" }} disabled={busyIdx === x.idx} onClick={() => regen(x.idx)}>
                    {busyIdx === x.idx ? "Regenerating…" : "Regenerate line"}
                  </button>
                </div>
              ))}
            </div>
          )}

          <Link to="/new" className="btn btn-secondary" style={{ textDecoration: "none" }}>Dub another video</Link>
        </aside>
      </div>
    </div>
  );
}
