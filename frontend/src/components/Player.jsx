import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { clock } from "../lib/format.js";

/** Video with a caption for the line being spoken and a segment timeline under it.
 *  Exposes seek(t) / playRange(a, b) to parents. */
const Player = forwardRef(function Player({ src, segments, activeIdx, onTime, captionKey = "src_text", label }, ref) {
  const video = useRef(null);
  const stopAt = useRef(null);
  const [t, setT] = useState(0);
  const [dur, setDur] = useState(0);

  useImperativeHandle(ref, () => ({
    seek(time) { if (video.current) { video.current.currentTime = time; } },
    playRange(a, b) {
      const v = video.current;
      if (!v) return;
      v.currentTime = a;
      stopAt.current = b;
      v.play().catch(() => {});
    },
    get element() { return video.current; },
  }));

  useEffect(() => {
    const v = video.current;
    if (!v) return;
    const tick = () => {
      setT(v.currentTime);
      onTime?.(v.currentTime);
      if (stopAt.current != null && v.currentTime >= stopAt.current) { v.pause(); stopAt.current = null; }
    };
    const meta = () => setDur(v.duration || 0);
    v.addEventListener("timeupdate", tick);
    v.addEventListener("seeked", tick);
    v.addEventListener("loadedmetadata", meta);
    return () => {
      v.removeEventListener("timeupdate", tick);
      v.removeEventListener("seeked", tick);
      v.removeEventListener("loadedmetadata", meta);
    };
  }, [onTime]);

  const current = segments.find((s) => t >= s.start_s && t <= s.end_s);
  const caption = current?.[captionKey]?.replace(/<[^>]+>\s*/g, "");
  const total = dur || segments.at(-1)?.end_s || 1;

  function seekFromBar(e) {
    const r = e.currentTarget.getBoundingClientRect();
    const x = Math.min(Math.max(0, e.clientX - r.left), r.width);
    if (video.current) video.current.currentTime = (x / r.width) * total;
  }

  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="player">
        <video ref={video} src={src} controls playsInline preload="metadata" aria-label={label} />
        {caption && <div className="player-caption" aria-hidden="true">{caption}</div>}
      </div>
      <div className="timeline" onClick={seekFromBar} role="slider" tabIndex={0}
           aria-label="Video timeline" aria-valuemin={0} aria-valuemax={Math.round(total)} aria-valuenow={Math.round(t)}
           onKeyDown={(e) => {
             if (!video.current) return;
             if (e.key === "ArrowRight") video.current.currentTime = Math.min(total, t + 2);
             if (e.key === "ArrowLeft") video.current.currentTime = Math.max(0, t - 2);
           }}>
        {segments.map((s) => (
          <span key={s.idx}
                className={`timeline-seg ${s.idx === activeIdx ? "active" : ""} ${s.flags?.length ? "flagged" : ""} ${s.keep_original ? "kept" : ""}`}
                style={{ left: `${(s.start_s / total) * 100}%`, width: `${((s.end_s - s.start_s) / total) * 100}%` }} />
        ))}
        <span className="timeline-head" style={{ left: `${(t / total) * 100}%` }} />
      </div>
      <div className="timeline-meta mono"><span>{clock(t)}</span><span>{segments.length} lines</span><span>{clock(total)}</span></div>
    </div>
  );
});

export default Player;
