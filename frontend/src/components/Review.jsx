import { useCallback, useRef, useState } from "react";
import Player from "./Player.jsx";
import { EMOTIONS, langName } from "../lib/catalog.js";
import { tc } from "../lib/format.js";
import { Arrow } from "./Icons.jsx";

function autosize(el) {
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${el.scrollHeight}px`;
}

export default function Review({ job, onContinue, saving }) {
  const [segs, setSegs] = useState(job.segments);
  const [active, setActive] = useState(null);
  const [follow, setFollow] = useState(true);
  const player = useRef(null);
  const rows = useRef({});

  const edit = (idx, patch) => setSegs((all) => all.map((s) => (s.idx === idx ? { ...s, ...patch } : s)));

  const onTime = useCallback((t) => {
    const cur = segs.find((s) => t >= s.start_s && t <= s.end_s);
    if (cur && cur.idx !== active) {
      setActive(cur.idx);
      if (follow) rows.current[cur.idx]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [segs, active, follow]);

  const changed = segs.filter((s, i) => {
    const o = job.segments[i];
    return o && (s.src_text !== o.src_text || s.emotion !== o.emotion || s.keep_original !== o.keep_original);
  }).length;

  return (
    <>
      <div className="review page-wide">
        <div className="player-col">
          <Player ref={player} src={job.video_url} segments={segs} activeIdx={active} onTime={onTime}
                  label={`Original video, ${langName(job.src_lang)}`} />
          {job.demo && (
            <p className="caption">Demo mode: these lines are sample text, not a transcript of your video.</p>
          )}
        </div>

        <section aria-labelledby="lines-h">
          <div className="seg-list-head">
            <div>
              <h2 id="lines-h" className="subhead" style={{ fontSize: 24 }}>Review the transcript</h2>
              <p className="body-sm dim" style={{ marginTop: 4 }}>
                Fix any wrong words and check each line's emotion. The dub copies the emotion you set here.
              </p>
            </div>
            <label className="keep">
              <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
              Follow playback
            </label>
          </div>

          <div className="seg-list">
            {segs.map((s) => (
              <div key={s.idx} ref={(el) => (rows.current[s.idx] = el)} className={`seg ${s.idx === active ? "active" : ""}`}>
                <div className="seg-time mono">
                  <button onClick={() => player.current?.playRange(s.start_s, s.end_s)} title="Play this line">
                    {tc(s.start_s)}
                  </button>
                  <div className="dim" style={{ fontSize: 12 }}>{(s.end_s - s.start_s).toFixed(1)} s</div>
                </div>
                <div className="seg-body">
                  <textarea
                    className="textarea" rows={1} value={s.src_text}
                    aria-label={`Line ${s.idx + 1} text`}
                    ref={autosize}
                    onChange={(e) => { edit(s.idx, { src_text: e.target.value }); autosize(e.target); }}
                    onFocus={() => { setActive(s.idx); player.current?.seek(s.start_s); }}
                  />
                  <div className="seg-tools">
                    <select
                      className={`emotion emo-${s.emotion}`} value={s.emotion}
                      aria-label={`Emotion for line ${s.idx + 1}`}
                      onChange={(e) => edit(s.idx, { emotion: e.target.value, emotion_overridden: true })}
                    >
                      {Object.entries(EMOTIONS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                    </select>
                    {s.intensity > 1 && s.emotion !== "neutral" && (
                      <span className="tag">{s.intensity === 3 ? "Strong" : "Clear"}</span>
                    )}
                    {s.nonverbal?.map((n) => <span key={n} className="tag">{n}</span>)}
                    <label className="keep" style={{ marginLeft: "auto" }}>
                      <input type="checkbox" checked={s.keep_original} onChange={(e) => edit(s.idx, { keep_original: e.target.checked })} />
                      Keep original audio
                    </label>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="action-bar">
        <div className="action-bar-inner">
          <span className="body-sm dim">
            {segs.length} lines{changed ? `, ${changed} edited` : ""}. Lines marked "keep original audio" won't be dubbed.
          </span>
          <button className="btn btn-primary" disabled={saving} onClick={() => onContinue(segs)}>
            {saving ? "Saving…" : "Choose a voice"} {!saving && <Arrow />}
          </button>
        </div>
      </div>
    </>
  );
}
