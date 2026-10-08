import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { clock } from "../lib/format.js";
import { Arrow } from "./Icons.jsx";

const MIN_TAKE = 2;

/** Record narration while the video plays. The take is anchored to the video time it
 *  started at (offset_s), so the backend can place every word exactly where it was said. */
export default function Narrate({ job, onSubmit, submitting }) {
  const video = useRef(null);
  const rec = useRef(null);
  const raf = useRef(null);
  const ctx = useRef(null);
  const previewAudio = useRef(null);
  const startedAt = useRef(0);

  const [t, setT] = useState(0);
  const [dur, setDur] = useState(job.duration_s || 0);
  const [state, setState] = useState("idle");      // idle | recording | denied
  const [level, setLevel] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [recFrom, setRecFrom] = useState(0);
  const [take, setTake] = useState(null);          // { blob, url, offset_s, duration_s, name }
  const [origAudio, setOrigAudio] = useState("mute");
  const [previewing, setPreviewing] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    const v = video.current;
    if (!v) return;
    const tick = () => setT(v.currentTime);
    const meta = () => setDur(v.duration || job.duration_s || 0);
    v.addEventListener("timeupdate", tick);
    v.addEventListener("seeked", tick);
    v.addEventListener("loadedmetadata", meta);
    return () => { v.removeEventListener("timeupdate", tick); v.removeEventListener("seeked", tick); v.removeEventListener("loadedmetadata", meta); };
  }, [job.duration_s]);

  useEffect(() => () => { cancelAnimationFrame(raf.current); ctx.current?.close(); }, []);

  useEffect(() => {
    const v = video.current;
    if (!v) return;
    v.muted = origAudio === "mute";
    v.volume = origAudio === "quiet" ? 0.25 : 1;
  }, [origAudio]);

  async function startRecording() {
    setErr(null);
    stopPreview();
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch {
      setState("denied");
      return;
    }
    const v = video.current;
    if (v.ended || v.currentTime >= (v.duration || dur) - 0.5) v.currentTime = 0;
    const offset = v.currentTime;
    setRecFrom(offset);

    // Level meter
    ctx.current?.close();
    ctx.current = new AudioContext();
    const analyser = ctx.current.createAnalyser();
    analyser.fftSize = 1024;
    ctx.current.createMediaStreamSource(stream).connect(analyser);
    const buf = new Float32Array(analyser.fftSize);
    const meter = () => {
      analyser.getFloatTimeDomainData(buf);
      let s = 0;
      for (const x of buf) s += x * x;
      setLevel(Math.min(1, Math.sqrt(s / buf.length) * 4));
      setElapsed((performance.now() - startedAt.current) / 1000);
      raf.current = requestAnimationFrame(meter);
    };

    const chunks = [];
    const r = new MediaRecorder(stream);
    r.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    r.onstop = () => {
      cancelAnimationFrame(raf.current);
      stream.getTracks().forEach((tr) => tr.stop());
      v.pause();
      setLevel(0);
      setState("idle");
      const duration = (performance.now() - startedAt.current) / 1000;
      if (duration < MIN_TAKE) { setErr(`That take was under ${MIN_TAKE} seconds. Record a little longer.`); return; }
      const blob = new Blob(chunks, { type: r.mimeType || "audio/webm" });
      setTake({ blob, url: URL.createObjectURL(blob), offset_s: offset, duration_s: duration, name: "Recording" });
    };
    rec.current = r;

    v.onended = () => rec.current?.state === "recording" && rec.current.stop();
    await v.play().catch(() => {});
    r.start(250);
    startedAt.current = performance.now();
    setElapsed(0);
    setState("recording");
    meter();
  }

  function stopRecording() { rec.current?.state === "recording" && rec.current.stop(); }

  function preview() {
    if (!take) return;
    if (previewing) { stopPreview(); return; }
    const v = video.current;
    const a = new Audio(take.url);
    previewAudio.current = a;
    v.currentTime = take.offset_s;
    v.play().catch(() => {});
    a.play().catch(() => {});
    setPreviewing(true);
    a.onended = () => stopPreview();
  }

  function stopPreview() {
    previewAudio.current?.pause();
    previewAudio.current = null;
    video.current?.pause();
    setPreviewing(false);
  }

  async function uploadFile(f) {
    setErr(null);
    if (!f) return;
    const url = URL.createObjectURL(f);
    const duration = await new Promise((res) => {
      const a = new Audio();
      a.preload = "metadata";
      a.onloadedmetadata = () => res(a.duration);
      a.onerror = () => res(null);
      a.src = url;
    });
    if (!duration) { setErr("That file couldn't be read as audio. Try a WAV, MP3 or M4A file."); return; }
    setTake({ blob: f, url, offset_s: +(video.current?.currentTime || 0).toFixed(2), duration_s: duration, name: f.name });
  }

  const total = dur || 1;
  const recording = state === "recording";
  const overrun = take && take.offset_s + take.duration_s > total + 0.25;

  return (
    <div className="narrate page-wide">
      <div className="stack" style={{ gap: 10 }}>
        <div className="player">
          <video ref={video} src={job.video_url} controls={!recording} playsInline preload="metadata" aria-label="Video to narrate" />
        </div>
        <div className="timeline" role="img" aria-label="Recorded take position">
          {take && (
            <span className="take-marker" style={{
              left: `${(take.offset_s / total) * 100}%`,
              width: `${(Math.min(take.duration_s, total - take.offset_s) / total) * 100}%`,
            }} />
          )}
          {recording && (
            <span className="take-marker" style={{
              left: `${(recFrom / total) * 100}%`, width: `${(Math.min(elapsed, total - recFrom) / total) * 100}%`,
            }} />
          )}
          <span className="timeline-head" style={{ left: `${(t / total) * 100}%` }} />
        </div>
        <div className="timeline-meta mono"><span>{clock(t)}</span><span>{clock(total)}</span></div>
      </div>

      <section className="card card-pad rec-panel" aria-labelledby="rec-h">
        <div>
          <h2 id="rec-h" className="subhead" style={{ fontSize: 24 }}>Record your narration</h2>
          <p className="body-sm muted" style={{ marginTop: 6 }}>
            Move the video to where you want to start, press record and talk while it plays. Each word is placed exactly where you said it.
          </p>
        </div>

        <div className="rec-row">
          <button className={`rec-big ${recording ? "on" : ""}`} onClick={recording ? stopRecording : startRecording}
                  disabled={submitting} aria-label={recording ? "Stop recording" : "Start recording"}>
            <span className="core" />
          </button>
          <div className="stack" style={{ gap: 4 }}>
            <span className="rec-time mono">{clock(recording ? elapsed : take?.duration_s || 0)}</span>
            {recording
              ? <span className="rec-live">Recording from {clock(recFrom)}</span>
              : <span className="body-sm dim">{take ? `Take starts at ${clock(take.offset_s)}` : `Starts at ${clock(t)}`}</span>}
          </div>
        </div>

        {recording && <div className="meter" aria-hidden="true"><span style={{ width: `${level * 100}%` }} /></div>}

        {state === "denied" && (
          <p className="body-sm" style={{ color: "var(--orange)" }}>Microphone access was blocked. Allow it for this page and try again.</p>
        )}
        {err && <p className="body-sm" style={{ color: "var(--orange)" }}>{err}</p>}

        {take && !recording && (
          <motion.div className="stack" style={{ gap: 12 }} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button className="btn btn-quiet btn-sm" onClick={preview}>{previewing ? "Stop preview" : "Preview with video"}</button>
              <button className="btn btn-quiet btn-sm" onClick={() => { stopPreview(); setTake(null); }}>Discard take</button>
            </div>
            {overrun && <p className="caption" style={{ color: "var(--orange)" }}>The take runs past the end of the video. The extra part will be cut.</p>}
          </motion.div>
        )}

        <hr className="divider" />

        <div className="field">
          <span className="field-label" id="orig-label">Video sound while recording</span>
          <div className="seg-control" role="group" aria-labelledby="orig-label" style={{ width: "fit-content" }}>
            <button aria-pressed={origAudio === "mute"} onClick={() => setOrigAudio("mute")}>Muted</button>
            <button aria-pressed={origAudio === "quiet"} onClick={() => setOrigAudio("quiet")}>Quiet</button>
          </div>
          <p className="caption">Use headphones if you leave the sound on, so it isn't picked up by your microphone.</p>
        </div>

        <label className="link-btn body-sm" style={{ cursor: "pointer", width: "fit-content" }}>
          Or upload a narration file instead
          <input type="file" accept="audio/*" hidden onChange={(e) => uploadFile(e.target.files[0])} />
        </label>
        {take && take.name !== "Recording" && (
          <label className="field">
            <span className="field-label">Start it at (seconds into the video)</span>
            <input className="num-input mono" type="number" min="0" step="0.1" value={take.offset_s}
                   onChange={(e) => setTake({ ...take, offset_s: Math.max(0, +e.target.value) })} style={{ maxWidth: 160 }} />
          </label>
        )}

        <button className="btn btn-primary" disabled={!take || recording || submitting}
                onClick={() => { stopPreview(); onSubmit(take); }} style={{ width: "100%" }}>
          {submitting ? "Uploading…" : "Use this take"} {!submitting && <Arrow />}
        </button>
        {job.demo && <p className="caption">Demo mode: your recording stays in the browser. The transcript will be sample text.</p>}
      </section>
    </div>
  );
}
