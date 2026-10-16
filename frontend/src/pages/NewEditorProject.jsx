// Create an editor project (R1–R4): pick a ready Library video, then the input — the video's own
// audio, a plain-text script (D1), or a narration recorded next (D12) — plus languages and voice.
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import * as editor from "../lib/editorApi.js";
import { refreshLibrary, stripExt, useLibrary } from "../lib/libraryStore.js";
import { SOURCE_LANGS, TARGET_LANGS, voicesFor } from "../lib/catalog.js";
import { clock } from "../lib/format.js";

const INPUTS = [
  { id: "video_audio", title: "Video's own audio", body: "Transcribe what's said, translate it, and re-voice it." },
  { id: "script", title: "A script", body: "Paste text; it's placed end to end along the video." },
  { id: "narration", title: "My narration", body: "Record one take over the video; it's cleaned, transcribed and re-voiced." },
];
const SRC = SOURCE_LANGS.filter((l) => l.code !== "auto");   // the editor needs a known language
const MAX_SCRIPT = 20000;

export default function NewEditorProject() {
  const nav = useNavigate();
  const lib = useLibrary();
  const [loaded, setLoaded] = useState(null);
  useEffect(() => { refreshLibrary().then(setLoaded); }, []);
  const videos = lib.filter((v) => v.remote && v.status === "READY");

  const [params] = useSearchParams();
  const [assetId, setAssetId] = useState(params.get("asset"));
  const [kind, setKind] = useState("video_audio");
  const [script, setScript] = useState("");
  const [src, setSrc] = useState("hi-IN");
  const [tgt, setTgt] = useState("hi-IN");
  const [voice, setVoice] = useState(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const voices = voicesFor(tgt);
  useEffect(() => { if (!voices.some((v) => v.id === voice)) setVoice(voices[0]?.id || null); }, [tgt]); // eslint-disable-line
  const asset = videos.find((v) => v.id === assetId);
  useEffect(() => { if (asset && !name) setName(stripExt(asset.name)); }, [assetId]); // eslint-disable-line

  const problems = [
    !asset && "Pick a video.",
    kind === "script" && !script.trim() && "Paste the script.",
    script.length > MAX_SCRIPT && `The script is over ${MAX_SCRIPT.toLocaleString()} characters.`,
    !voice && "Pick a voice.",
    !name.trim() && "Name the project.",
  ].filter(Boolean);

  async function create() {
    if (problems.length || busy) return;
    setBusy(true); setErr(null);
    try {
      const p = await editor.createProject({
        asset_id: assetId, name: name.trim(), input_kind: kind,
        script_text: kind === "script" ? script : null,
        src_lang: src, tgt_lang: tgt, voice: { mode: "persona", voice_id: voice },
      });
      nav(`/editor/${p.id}`);
    } catch (e) { setErr(e.message); setBusy(false); }
  }

  return (
    <section className="page ne-page">
      <header className="ne-head">
        <h1 className="pg-title">New project</h1>
        <p className="pg-sub">Choose a video, tell Vani what the voice should say, and pick the language and voice.</p>
      </header>

      <Step n={1} title="Video" hint={asset ? asset.name : "Pick one of your Library videos."}>
        {loaded === false && <div className="banner error"><span className="banner-dot" /><span>Couldn't reach the Library. Is the media service running?</span></div>}
        {loaded && videos.length === 0 && (
          <div className="ne-empty">No ready videos yet. <Link to="/library">Upload one in the Library</Link>.</div>
        )}
        {loaded && assetId && !asset && (
          <p className="ne-note">That video isn't ready yet, or it was removed. Pick another one.</p>
        )}
        <div className="ne-videos">
          {videos.map((v) => (
            <button key={v.id} className={`ne-video ${assetId === v.id ? "on" : ""}`} onClick={() => setAssetId(v.id)}
                    aria-pressed={assetId === v.id}>
              <span className="ne-thumb" style={{ background: v.cover || "var(--surface-2)" }}>
                {v.duration_s && <span className="ne-dur mono">{clock(v.duration_s)}</span>}
              </span>
              <span className="ne-video-name" title={v.name}>{v.name}</span>
            </button>
          ))}
        </div>
      </Step>

      <Step n={2} title="What should the voice say?">
        <div className="ne-inputs" role="radiogroup" aria-label="Input">
          {INPUTS.map((i) => (
            <button key={i.id} role="radio" aria-checked={kind === i.id} className={`ne-input ${kind === i.id ? "on" : ""}`}
                    onClick={() => setKind(i.id)}>
              <span className="ne-input-title">{i.title}</span>
              <span className="ne-input-body">{i.body}</span>
            </button>
          ))}
        </div>
        {kind === "script" && (
          <div className="ne-field" style={{ marginTop: 14 }}>
            <label className="ne-label" htmlFor="ne-script">Script</label>
            <textarea id="ne-script" className="input ne-textarea" rows={8} value={script}
                      onChange={(e) => setScript(e.target.value)} placeholder="Paste or type the script…" />
            <span className={`ne-count ${script.length > MAX_SCRIPT ? "over" : ""}`}>
              {script.length.toLocaleString()} / {MAX_SCRIPT.toLocaleString()}
            </span>
          </div>
        )}
        {kind === "narration" && <p className="ne-note">You'll record your take right after creating the project.</p>}
      </Step>

      <Step n={3} title="Languages and voice" hint="The language is fixed once the project is created. The voice can be changed any time.">
        <div className="ne-grid">
          <div className="ne-field">
            <label className="ne-label" htmlFor="ne-src">{kind === "script" ? "Script language" : "Spoken language"}</label>
            <select id="ne-src" className="select" value={src} onChange={(e) => setSrc(e.target.value)}>
              {SRC.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
            </select>
          </div>
          <div className="ne-field">
            <label className="ne-label" htmlFor="ne-tgt">Voice-over language</label>
            <select id="ne-tgt" className="select" value={tgt} onChange={(e) => setTgt(e.target.value)}>
              {TARGET_LANGS.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
            </select>
          </div>
          <div className="ne-field">
            <label className="ne-label" htmlFor="ne-voice">Voice</label>
            <select id="ne-voice" className="select" value={voice || ""} onChange={(e) => setVoice(e.target.value)}>
              {voices.map((v) => <option key={v.id} value={v.id}>{v.name} · {v.gender}</option>)}
            </select>
          </div>
        </div>
      </Step>

      <Step n={4} title="Name">
        <div className="ne-field">
          <label className="ne-label" htmlFor="ne-name">Project name</label>
          <input id="ne-name" className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
        </div>
      </Step>

      {err && <div className="banner error" role="alert" style={{ marginTop: 20 }}><span className="banner-dot" /><span>{err}</span></div>}
      <div className="ne-submit">
        <button className="btn btn-primary btn-ctl" onClick={create} disabled={busy || problems.length > 0}>
          {busy ? "Creating…" : kind === "narration" ? "Create and record" : "Create and generate"}
        </button>
        {problems.length > 0 && <span className="ne-note">{problems[0]}</span>}
      </div>
    </section>
  );
}

function Step({ n, title, hint, children }) {
  return (
    <section className="ne-step" aria-labelledby={`ne-step-${n}`}>
      <div className="ne-step-head">
        <span className="ne-step-n" aria-hidden="true">{n}</span>
        <div>
          <h2 id={`ne-step-${n}`} className="ne-step-title">{title}</h2>
          {hint && <p className="ne-step-hint">{hint}</p>}
        </div>
      </div>
      <div className="ne-step-body">{children}</div>
    </section>
  );
}
