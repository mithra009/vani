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
    <section className="page">
      <h1 className="title">New project</h1>

      <h2 className="field-label">1 · Video</h2>
      {loaded === false && <div className="banner error"><span className="banner-dot" />Couldn't reach the Library. Is the media service running?</div>}
      {loaded && videos.length === 0 && <p className="dim">No ready videos yet. <Link to="/library">Upload one in the Library</Link>.</p>}
      {loaded && assetId && !asset && (
        <p className="caption dim">That video isn't ready yet (or was removed). Pick another, or wait for processing to finish.</p>
      )}
      <div className="ne-videos">
        {videos.map((v) => (
          <button key={v.id} className={`ne-video ${assetId === v.id ? "on" : ""}`} onClick={() => setAssetId(v.id)}>
            <span className="ne-thumb" style={{ background: v.cover || "var(--surface-2)" }} />
            <span className="ne-video-name">{v.name}</span>
            {v.duration_s && <span className="mono dim">{clock(v.duration_s)}</span>}
          </button>
        ))}
      </div>

      <h2 className="field-label">2 · What should the voice say?</h2>
      <div className="ne-inputs">
        {INPUTS.map((i) => (
          <button key={i.id} className={`ne-input ${kind === i.id ? "on" : ""}`} onClick={() => setKind(i.id)}>
            <strong>{i.title}</strong><span className="body-sm dim">{i.body}</span>
          </button>
        ))}
      </div>
      {kind === "script" && (
        <>
          <textarea className="input" rows={8} value={script} onChange={(e) => setScript(e.target.value)}
                    placeholder="Paste or type the script…" style={{ marginTop: 12 }} />
          <span className={`caption ${script.length > MAX_SCRIPT ? "" : "dim"}`}>{script.length.toLocaleString()} / {MAX_SCRIPT.toLocaleString()}</span>
        </>
      )}
      {kind === "narration" && <p className="caption dim" style={{ marginTop: 8 }}>You'll record right after creating the project.</p>}

      <h2 className="field-label">3 · Languages and voice</h2>
      <div className="ne-row">
        <label className="body-sm">{kind === "script" ? "Script language" : "Spoken language"}
          <select className="select" value={src} onChange={(e) => setSrc(e.target.value)}>
            {SRC.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
          </select>
        </label>
        <label className="body-sm">Voice-over language
          <select className="select" value={tgt} onChange={(e) => setTgt(e.target.value)}>
            {TARGET_LANGS.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
          </select>
        </label>
        <label className="body-sm">Voice
          <select className="select" value={voice || ""} onChange={(e) => setVoice(e.target.value)}>
            {voices.map((v) => <option key={v.id} value={v.id}>{v.name} · {v.gender}</option>)}
          </select>
        </label>
      </div>
      <p className="caption dim">The language is fixed once the project is created; the voice can be changed any time.</p>

      <h2 className="field-label">4 · Name</h2>
      <input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />

      {err && <div className="banner error" role="alert" style={{ marginTop: 16 }}><span className="banner-dot" /><span>{err}</span></div>}
      <div style={{ marginTop: 20, display: "flex", gap: 12, alignItems: "center" }}>
        <button className="btn btn-primary" onClick={create} disabled={busy || problems.length > 0}>
          {busy ? "Creating…" : kind === "narration" ? "Create and record" : "Create and generate"}
        </button>
        {problems.length > 0 && <span className="caption dim">{problems[0]}</span>}
      </div>
    </section>
  );
}
