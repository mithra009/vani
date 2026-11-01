// Compact audio player: play/pause, seekable progress, elapsed / total. Replaces the browser's
// native <audio controls>. `src` may be a URL or a function returning a Promise<URL> (fetched on
// first play, so signed URLs are only requested when needed).
import { useEffect, useRef, useState } from "react";
import { Loader } from "./Icons.jsx";
import { clock } from "../lib/format.js";

// Only one player sounds at a time: starting one pauses whichever was playing (e.g. two chunks).
let current = null;          // { audio, pause() } of the player now playing

export default function AudioPlayer({ src, label = "Audio", autoPlay = false, onError, compact = false }) {
  const audio = useRef(null);
  const bar = useRef(null);
  const [state, setState] = useState("idle");        // idle | loading | playing | paused | error
  const [t, setT] = useState(0);
  const [dur, setDur] = useState(0);

  // A loader function is re-created on every parent render (each live update), so only a new URL
  // string resets the player; callers whose function source really changes remount it with a key
  // (the chunk list keys players by revision). Resetting on function identity stopped playback
  // whenever another chunk finished voicing.
  const srcFn = useRef(src);
  srcFn.current = src;
  const srcKey = typeof src === "function" ? null : src;

  useEffect(() => () => {
    if (current?.audio === audio.current) current = null;
    audio.current?.pause(); audio.current = null;
  }, []);
  useEffect(() => { audio.current?.pause(); audio.current = null; setState("idle"); setT(0); setDur(0); }, [srcKey]);
  useEffect(() => { if (autoPlay) toggle(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function ensure() {
    if (audio.current) return audio.current;
    setState("loading");
    const s = srcFn.current;
    const url = typeof s === "function" ? await s() : s;
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
      if (current && current.audio !== a) current.pause();
      current = { audio: a, pause: () => { a.pause(); setState("paused"); } };
      await a.play();
      setState("playing");
    } catch (e) {
      // AbortError: this play() was cut short by a pause() (e.g. the user pressed pause again);
      // nothing failed, so it isn't reported.
      if (e.name === "AbortError") { setState(audio.current?.paused === false ? "playing" : "paused"); return; }
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
        {state === "loading" ? <Loader size={14} /> : playing ? (
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
