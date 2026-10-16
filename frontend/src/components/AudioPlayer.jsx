// Compact audio player: play/pause, seekable progress, elapsed / total. Replaces the browser's
// native <audio controls>. `src` may be a URL or a function returning a Promise<URL> (fetched on
// first play, so signed URLs are only requested when needed).
import { useEffect, useRef, useState } from "react";
import { clock } from "../lib/format.js";

export default function AudioPlayer({ src, label = "Audio", autoPlay = false, onError, compact = false }) {
  const audio = useRef(null);
  const bar = useRef(null);
  const [state, setState] = useState("idle");        // idle | loading | playing | paused | error
  const [t, setT] = useState(0);
  const [dur, setDur] = useState(0);

  useEffect(() => () => { audio.current?.pause(); audio.current = null; }, []);
  // A new source (e.g. regenerated chunk) resets the player.
  useEffect(() => { audio.current?.pause(); audio.current = null; setState("idle"); setT(0); setDur(0); }, [src]);
  useEffect(() => { if (autoPlay) toggle(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function ensure() {
    if (audio.current) return audio.current;
    setState("loading");
    const url = typeof src === "function" ? await src() : src;
    const a = new Audio(url);
    a.preload = "auto";
    a.ontimeupdate = () => setT(a.currentTime);
    a.onloadedmetadata = () => setDur(Number.isFinite(a.duration) ? a.duration : 0);
    a.onended = () => { setState("paused"); setT(0); a.currentTime = 0; };
    a.onerror = () => { setState("error"); onError?.(`${label} couldn't be played.`); };
    audio.current = a;
    return a;
  }

  async function toggle() {
    try {
      const a = await ensure();
      if (!a.paused) { a.pause(); setState("paused"); return; }
      await a.play();
      setState("playing");
    } catch (e) {
      setState("error");
      onError?.(`${label} couldn't be played: ${e.message}`);
    }
  }

  function seek(e) {
    const a = audio.current;
    if (!a || !dur) return;
    const r = bar.current.getBoundingClientRect();
    a.currentTime = Math.max(0, Math.min(dur, ((e.clientX - r.left) / r.width) * dur));
    setT(a.currentTime);
  }

  const pct = dur ? (t / dur) * 100 : 0;
  const playing = state === "playing";
  return (
    <div className={`ap ${compact ? "ap-compact" : ""} ${state === "error" ? "ap-error" : ""}`}>
      <button className="ap-btn" onClick={toggle} aria-label={playing ? `Pause ${label}` : `Play ${label}`}
              disabled={state === "loading"}>
        {state === "loading" ? <span className="ap-spin" /> : playing ? (
          <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></svg>
        ) : (
          <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13l10.5-6.5z" /></svg>
        )}
      </button>
      <div className="ap-track" ref={bar} onPointerDown={seek} role="slider" aria-label={`${label} position`}
           aria-valuemin={0} aria-valuemax={Math.round(dur)} aria-valuenow={Math.round(t)} tabIndex={audio.current ? 0 : -1}
           onKeyDown={(e) => {
             const a = audio.current;
             if (!a) return;
             if (e.key === "ArrowRight") a.currentTime = Math.min(dur, a.currentTime + 2);
             if (e.key === "ArrowLeft") a.currentTime = Math.max(0, a.currentTime - 2);
           }}>
        <span className="ap-fill" style={{ width: `${pct}%` }} />
        <span className="ap-knob" style={{ left: `${pct}%` }} />
      </div>
      <span className="ap-time mono">{clock(t)}{dur ? ` / ${clock(dur)}` : ""}</span>
    </div>
  );
}
