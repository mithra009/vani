// One-take narration (D12): the video plays from 0 while the mic records; the take is uploaded
// to a signed URL and the server cleans it (noise reduction, amplification) before STT (R4).
import { useEffect, useRef, useState } from "react";
import { Loader } from "./Icons.jsx";
import * as editor from "../lib/editorApi.js";
import { uploadToStorage } from "../lib/libraryStore.js";
import { api } from "../lib/api.js";
import { clock } from "../lib/format.js";
import AudioPlayer from "./AudioPlayer.jsx";

const MIN_TAKE_S = 2;

export default function NarrationTake({ project }) {
  const video = useRef(null);
  const rec = useRef(null);
  const started = useRef(0);
  const [src, setSrc] = useState(null);
  const [state, setState] = useState("idle");      // idle | recording | review | uploading
  const [take, setTake] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const [progress, setProgress] = useState(0);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.assetPreviewUrl(project.asset_id)
      .then((r) => setSrc(r.url))
      .catch((e) => setErr(`The video can't load: ${e.message}`));
  }, [project.asset_id]);

  useEffect(() => {
    if (state !== "recording") return;
    const id = setInterval(() => setElapsed((performance.now() - started.current) / 1000), 200);
    return () => clearInterval(id);
  }, [state]);

  async function start() {
    setErr(null);
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch (e) {
      setErr(`Microphone unavailable: ${e.message}. Allow microphone access and try again.`);
      return;
    }
    const parts = [];
    const r = new MediaRecorder(stream);
    r.ondataavailable = (e) => e.data.size && parts.push(e.data);
    r.onerror = (e) => setErr(`Recording failed: ${e.error?.message || "unknown error"}`);
    r.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      video.current?.pause();
      const dur = (performance.now() - started.current) / 1000;
      if (dur < MIN_TAKE_S) { setErr(`That take was under ${MIN_TAKE_S} s. Record again.`); setState("idle"); return; }
      const blob = new Blob(parts, { type: r.mimeType || "audio/webm" });
      setTake({ blob, url: URL.createObjectURL(blob), duration: dur });
      setState("review");
    };
    rec.current = r;
    const v = video.current;
    v.currentTime = 0;                                 // the take is anchored at source 0
    v.muted = true;
    v.onended = () => r.state === "recording" && r.stop();
    try { await v.play(); } catch (e) { setErr(`The video can't play: ${e.message}`); stream.getTracks().forEach((t) => t.stop()); return; }
    r.start(250);
    started.current = performance.now();
    setElapsed(0);
    setState("recording");
  }

  async function submit() {
    if (!take) return;
    setState("uploading"); setErr(null);
    const ext = take.blob.type.includes("ogg") ? "ogg" : take.blob.type.includes("mp4") ? "m4a" : "webm";
    try {
      const init = await editor.narrationInit(project.id, ext);
      const file = new File([take.blob], `narration.${ext}`, { type: take.blob.type });
      await uploadToStorage(file, init.uploadUrl, setProgress, init.uploadMethod);
      await editor.narrationComplete(project.id, ext);     // project → generating; SSE takes over
    } catch (e) {
      setErr(`Upload failed: ${e.message}. Your take is kept; try again.`);
      setState("review");
    }
  }

  const total = Number(project.duration_s) || 0;
  const shown = state === "review" && take ? take.duration : elapsed;

  return (
    <div className="narr">
      <div className="narr-stage">
        {src ? <video ref={video} src={src} playsInline className="narr-video" />
          : <div className="narr-video narr-video-empty"><Loader size={28} /> Loading video…</div>}
      </div>

      <aside className="narr-panel" aria-label="Recording">
        <h2 className="narr-title">Record your narration</h2>
        <ol className="narr-steps">
          <li>Press <b>Start recording</b>. The video plays from the start, muted.</li>
          <li>Speak over it in one take. Recording stops when the video ends, or press Stop.</li>
          <li>Listen back, then use the take or record again.</li>
        </ol>

        <div className={`narr-clock ${state === "recording" ? "on" : ""}`}>
          <span className="narr-clock-label">{state === "recording" ? <span className="narr-rec">● REC</span> : state === "review" ? "Your take" : "Ready"}</span>
          <span className="narr-clock-time mono">{clock(shown)}{total > 0 && <span className="dim"> / {clock(total)}</span>}</span>
        </div>
        {total > 0 && <div className="bar"><span style={{ width: `${Math.min(100, (shown / total) * 100)}%` }} /></div>}

        <div className="narr-controls">
          {state === "idle" && <button className="btn btn-primary narr-main" onClick={start} disabled={!src}>● Start recording</button>}
          {state === "recording" && <button className="btn narr-main" onClick={() => rec.current?.stop()}>■ Stop</button>}
          {state === "review" && take && (
            <>
              <AudioPlayer src={take.url} label="Your take" onError={setErr} />
              <div className="narr-row">
                <button className="btn" onClick={() => { URL.revokeObjectURL(take.url); setTake(null); setState("idle"); }}>Record again</button>
                <button className="btn btn-primary" onClick={submit}>Use this take</button>
              </div>
            </>
          )}
          {state === "uploading" && <span className="body-sm loader-inline"><Loader size={14} /> Uploading {Math.round(progress * 100)}%…</span>}
        </div>

        <p className="caption narr-tip">Use headphones if you can, so the mic only hears you. Background noise is cleaned up afterwards.</p>
        {err && <div className="banner error" role="alert"><span className="banner-dot" /><span>{err}</span></div>}
      </aside>
    </div>
  );
}
