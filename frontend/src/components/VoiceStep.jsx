import { useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { api } from "../lib/api.js";
import { langName, voicesFor } from "../lib/catalog.js";
import { clock } from "../lib/format.js";
import { Play, Pause } from "./Icons.jsx";

const AVATAR = ["#ffd60a", "#64d2ff", "#30d158", "#ff9f0a", "#bf5af2", "#ff375f", "#5e5ce6", "#66d4cf"];

function bestReference(segments) {
  // Longest run of consecutive non-kept lines up to 30 s, preferring calm delivery.
  let best = null;
  for (let i = 0; i < segments.length; i++) {
    let j = i;
    while (j + 1 < segments.length && segments[j + 1].end_s - segments[i].start_s <= 30) j++;
    const run = segments.slice(i, j + 1);
    const len = segments[j].end_s - segments[i].start_s;
    const calm = run.filter((s) => s.emotion === "neutral").length;
    const score = Math.min(len, 30) + calm * 2;
    if (len >= 5 && (!best || score > best.score)) best = { start: segments[i].start_s, end: segments[j].end_s, score };
  }
  return best || { start: 0, end: Math.min(15, segments.at(-1)?.end_s || 15) };
}

function Recorder({ onDone }) {
  const [state, setState] = useState("idle");   // idle | recording | denied
  const [secs, setSecs] = useState(0);
  const rec = useRef(null);
  const timer = useRef(null);

  async function start() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks = [];
      const r = new MediaRecorder(stream);
      r.ondataavailable = (e) => chunks.push(e.data);
      r.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        clearInterval(timer.current);
        setState("idle");
        onDone(new Blob(chunks, { type: r.mimeType }));
      };
      rec.current = r;
      r.start();
      setSecs(0);
      setState("recording");
      const t0 = Date.now();
      timer.current = setInterval(() => {
        const s = (Date.now() - t0) / 1000;
        setSecs(s);
        if (s >= 30) r.stop();
      }, 200);
    } catch {
      setState("denied");
    }
  }

  return (
    <div className="stack" style={{ gap: 8 }}>
      <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
        {state === "recording" ? (
          <button className="btn btn-quiet btn-sm" onClick={() => rec.current?.stop()} disabled={secs < 5}>
            <span style={{ width: 9, height: 9, borderRadius: 2, background: "var(--red)" }} /> Stop
          </button>
        ) : (
          <button className="btn btn-quiet btn-sm" onClick={start}>
            <span style={{ width: 9, height: 9, borderRadius: "50%", background: "var(--red)" }} /> Start recording
          </button>
        )}
        <span className="mono body-sm dim">{state === "recording" ? `${secs.toFixed(1)} s` : ""}</span>
      </div>
      <p className="caption">
        {state === "denied"
          ? "Microphone access was blocked. Allow it for this page and try again."
          : state === "recording"
            ? secs < 5 ? "Keep talking. You can stop after 5 seconds." : "Stops automatically at 30 seconds."
            : "Read anything naturally in a quiet room for 10 to 20 seconds."}
      </p>
    </div>
  );
}

export default function VoiceStep({ job, mode, onBack, onStart, starting }) {
  const voices = useMemo(() => voicesFor(job.tgt_lang), [job.tgt_lang]);
  const narrate = job.mode === "narrate";
  const sameLang = job.tgt_lang === job.src_lang;
  const [kind, setKind] = useState(narrate && sameLang ? "own" : "persona");   // own | persona | clone
  const [gender, setGender] = useState("All");
  const [voiceId, setVoiceId] = useState(voices[0]?.id);
  const [bg, setBg] = useState("duck");
  const ref = useMemo(() => bestReference(job.segments), [job.segments]);
  const [refStart, setRefStart] = useState(+ref.start.toFixed(1));
  const [refEnd, setRefEnd] = useState(+ref.end.toFixed(1));
  const [consent, setConsent] = useState(false);
  const [cloneSrc, setCloneSrc] = useState("video");   // video | upload | record
  const [sample, setSample] = useState(null);          // { blob, url, duration, name }
  const [sampleErr, setSampleErr] = useState(null);
  const [playing, setPlaying] = useState(null);
  const audio = useRef(null);

  const shown = voices.filter((v) => gender === "All" || v.gender === gender);
  const refLen = refEnd - refStart;
  const refOk = refLen >= 5 && refLen <= 30;
  const sampleOk = !!sample && sample.duration >= 5 && sample.duration <= 30;
  const cloneReady = cloneSrc === "video" ? refOk : sampleOk;
  const ready = kind === "own" ? sameLang : kind === "persona" ? !!voiceId : consent && cloneReady;

  async function takeSample(blob, name) {
    setSampleErr(null);
    const url = URL.createObjectURL(blob);
    const duration = await new Promise((res) => {
      const a = new Audio();
      a.preload = "metadata";
      a.onloadedmetadata = () => {
        // MediaRecorder webm reports Infinity until seeked to the end.
        if (a.duration === Infinity) { a.currentTime = 1e9; a.ontimeupdate = () => { a.ontimeupdate = null; res(a.duration); }; }
        else res(a.duration);
      };
      a.onerror = () => res(null);
      a.src = url;
    });
    if (duration == null) { setSampleErr("That file couldn't be read as audio. Try a WAV, MP3 or M4A file."); return; }
    if (duration < 5 || duration > 30) setSampleErr(`The sample is ${duration.toFixed(1)} s. It needs to be 5 to 30 seconds.`);
    setSample({ blob, url, duration, name });
  }
  const dubbed = job.segments.filter((s) => !s.keep_original).length;

  function preview(v) {
    if (mode !== "live") return;
    if (playing === v.id) { audio.current?.pause(); setPlaying(null); return; }
    audio.current?.pause();
    audio.current = new Audio(api.previewUrl(v.id, job.tgt_lang));
    audio.current.onended = () => setPlaying(null);
    audio.current.play().then(() => setPlaying(v.id)).catch(() => setPlaying(null));
  }

  function start() {
    onStart({
      voice: kind === "own" ? { mode: "own" } : kind === "persona"
        ? { mode: "persona", voice_id: voiceId }
        : cloneSrc === "video"
          ? { mode: "clone", source: "video", reference: { start_s: refStart, end_s: refEnd }, consent: true }
          : { mode: "clone", source: cloneSrc, sample: sample.blob, consent: true },
      bg_mode: bg,
    });
  }

  return (
    <div className="voice-layout page-wide">
      <section aria-labelledby="voice-h">
        <h2 id="voice-h" className="subhead" style={{ fontSize: 24 }}>Choose a voice</h2>
        <p className="body-sm dim" style={{ marginTop: 4, marginBottom: 22 }}>
          {narrate
            ? "Keep your own recording, or have your words spoken by a Gnani voice or a clone."
            : "The voice stays the same for the whole video. Emotion comes from how each line is spoken."}
        </p>

        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "center", marginBottom: 22 }}>
          <div className="seg-control" role="group" aria-label="Voice type">
            {narrate && <button aria-pressed={kind === "own"} onClick={() => setKind("own")}>My recording</button>}
            <button aria-pressed={kind === "persona"} onClick={() => setKind("persona")}>Gnani voices</button>
            <button aria-pressed={kind === "clone"} onClick={() => setKind("clone")}>Clone a voice</button>
          </div>
          {kind === "persona" && (
            <div className="seg-control" role="group" aria-label="Filter by voice">
              {["All", "Female", "Male"].map((g) => (
                <button key={g} aria-pressed={gender === g} onClick={() => setGender(g)}>{g}</button>
              ))}
            </div>
          )}
        </div>

        {kind === "own" ? (
          <div className="card card-pad stack" style={{ gap: 12 }}>
            <h3 style={{ fontSize: 19, fontWeight: 600 }}>Use your own recording</h3>
            {sameLang ? (
              <>
                <p className="body-sm muted">
                  Your narration goes into the video exactly where you said it, with background noise reduced and loudness evened out.
                  The transcript becomes subtitles, so your edits change the subtitles, not the audio.
                </p>
                {job.narration && (
                  <audio src={job.narration.url} controls style={{ width: "100%" }} aria-label="Your recording" />
                )}
              </>
            ) : (
              <p className="body-sm" style={{ color: "var(--orange)" }}>
                Your recording is in {langName(job.src_lang)}, but you chose {langName(job.tgt_lang)} as the final language.
                To keep your voice in {langName(job.tgt_lang)}, use "Clone a voice" with your own recording as the sample.
              </p>
            )}
          </div>
        ) : kind === "persona" ? (
          <div className="voice-grid" role="radiogroup" aria-label={`${langName(job.tgt_lang)} voices`}>
            {shown.map((v) => (
              <motion.div key={v.id} layout initial={{ opacity: 0 }} animate={{ opacity: 1 }} style={{ position: "relative" }}>
                <button className="voice" role="radio" aria-checked={voiceId === v.id} onClick={() => setVoiceId(v.id)} style={{ width: "100%" }}>
                  <span className="voice-avatar" style={{ background: AVATAR[v.name.charCodeAt(0) % AVATAR.length] }}>{v.name[0]}</span>
                  <span>
                    <span className="voice-name" style={{ display: "block" }}>{v.name}</span>
                    <span className="voice-meta">{v.gender}, {v.language}</span>
                  </span>
                </button>
                <button className="voice-play" onClick={() => preview(v)} disabled={mode !== "live"}
                        aria-label={`Preview ${v.name}`} title={mode === "live" ? `Preview ${v.name}` : "Previews need the backend running"}>
                  {playing === v.id ? <Pause /> : <Play />}
                </button>
              </motion.div>
            ))}
            {shown.length === 0 && <p className="muted">No {gender.toLowerCase()} voices for {langName(job.tgt_lang)}.</p>}
          </div>
        ) : (
          <div className="card card-pad clone-box">
            <div>
              <h3 style={{ fontSize: 19, fontWeight: 600 }}>Clone a voice</h3>
              <p className="body-sm muted" style={{ marginTop: 6 }}>
                Gnani voice cloning needs 5 to 30 seconds of clean speech: from this video, a file, or a recording.
              </p>
            </div>
            <div className="seg-control" role="group" aria-label="Voice sample source" style={{ width: "fit-content" }}>
              <button aria-pressed={cloneSrc === "video"} onClick={() => setCloneSrc("video")}>{narrate ? "From my narration" : "From this video"}</button>
              <button aria-pressed={cloneSrc === "upload"} onClick={() => setCloneSrc("upload")}>Upload a sample</button>
              <button aria-pressed={cloneSrc === "record"} onClick={() => setCloneSrc("record")}>Record</button>
            </div>
            {cloneSrc === "upload" && (
              <label className="dropzone" style={{ minHeight: 120, padding: 20, borderRadius: 14 }}>
                <span className="body-sm">{sample && cloneSrc === "upload" ? sample.name : "Choose an audio file"}</span>
                <span className="caption">WAV, MP3 or M4A, 5 to 30 seconds, one speaker, no music.</span>
                <input type="file" accept="audio/*" hidden onChange={(e) => e.target.files[0] && takeSample(e.target.files[0], e.target.files[0].name)} />
              </label>
            )}
            {cloneSrc === "record" && <Recorder onDone={(b) => takeSample(b, "Recording")} />}
            {cloneSrc !== "video" && sample && (
              <div className="stack" style={{ gap: 6 }}>
                <audio src={sample.url} controls style={{ width: "100%" }} />
                <p className="caption mono">{sample.duration.toFixed(1)} s</p>
              </div>
            )}
            {cloneSrc !== "video" && sampleErr && <p className="body-sm" style={{ color: "var(--orange)" }}>{sampleErr}</p>}
            {cloneSrc === "video" && (<>
            <p className="body-sm dim">We picked the clearest stretch of the speaker. You can change it.</p>
            <div className="range-row">
              <label className="field">
                <span className="field-label">Start (seconds)</span>
                <input className="num-input mono" type="number" step="0.1" min="0" value={refStart}
                       onChange={(e) => setRefStart(+e.target.value)} />
              </label>
              <label className="field">
                <span className="field-label">End (seconds)</span>
                <input className="num-input mono" type="number" step="0.1" min="0" value={refEnd}
                       onChange={(e) => setRefEnd(+e.target.value)} />
              </label>
            </div>
            <p className={`body-sm ${refOk ? "dim" : ""}`} style={{ color: refOk ? undefined : "var(--orange)" }}>
              {refOk ? `Using ${clock(refStart)} to ${clock(refEnd)} (${refLen.toFixed(1)} s).` : "Choose a stretch between 5 and 30 seconds long."}
            </p>
            </>)}
            <hr className="divider" />
            <label className="check">
              <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
              <span>This is my voice, or I have this person's permission to clone it. The dubbed video will be labelled as using an AI-generated voice.</span>
            </label>
          </div>
        )}

        <div style={{ marginTop: 28 }}>
          <button className="link-btn body-sm" onClick={onBack}>Back to the transcript</button>
        </div>
      </section>

      <aside className="side-card">
        <div className="card card-pad stack" style={{ gap: 18 }}>
          <h3 style={{ fontSize: 19, fontWeight: 600 }}>Summary</h3>
          <dl className="stack" style={{ gap: 10, margin: 0 }}>
            <div className="summary-row"><dt>From</dt><dd>{langName(job.src_lang)}</dd></div>
            <div className="summary-row"><dt>To</dt><dd>{langName(job.tgt_lang)}</dd></div>
            <div className="summary-row"><dt>{kind === "own" ? "Lines" : "Lines to voice"}</dt><dd className="mono">{dubbed} of {job.segments.length}</dd></div>
            <div className="summary-row"><dt>Length</dt><dd className="mono">{clock(job.duration_s)}</dd></div>
            <div className="summary-row">
              <dt>Voice</dt>
              <dd>{kind === "own" ? "Your recording" : kind === "persona" ? voiceId || "–" : cloneSrc === "video" ? (narrate ? "Clone of your narration" : "Clone of the speaker") : "Clone from your sample"}</dd>
            </div>
          </dl>
          <hr className="divider" />
          <div className="field">
            <span className="field-label" id="bg-label">Original audio</span>
            <div className="seg-control" role="group" aria-labelledby="bg-label" style={{ width: "fit-content" }}>
              <button aria-pressed={bg === "duck"} onClick={() => setBg("duck")}>Lower under dub</button>
              <button aria-pressed={bg === "mute"} onClick={() => setBg("mute")}>Remove</button>
            </div>
            <p className="caption">
              {bg === "duck" ? "Music and sounds stay, quieter whenever the new voice speaks." : "Only the new voice. Music and sound effects are removed too."}
            </p>
          </div>
          <button className="btn btn-primary" disabled={!ready || starting} onClick={start} style={{ width: "100%" }}>
            {starting ? "Starting…" : kind === "own" ? "Add narration to video" : "Dub video"}
          </button>
          {!ready && kind === "clone" && <p className="caption">Add a 5 to 30 second voice sample and confirm consent to continue.</p>}
        </div>
      </aside>
    </div>
  );
}
