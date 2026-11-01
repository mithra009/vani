// Lines that run into the next one, and the user's choice of fix: speed them up exactly enough, or
// let Gemini shorten the wording (meaning kept). Nothing changes until the user picks one.
import { useEffect, useState } from "react";
import { Loader } from "./Icons.jsx";
import * as editor from "../lib/editorApi.js";

export default function OverlapFix({ project, chunks, compact = false }) {
  const [lines, setLines] = useState([]);
  const [busy, setBusy] = useState(null);           // "speed" | "shorten" while a fix runs
  const [note, setNote] = useState(null);           // { kind: "ok" | "err", text }

  // Re-check whenever any chunk changes (a re-voice changes its length) or the project settles.
  const stamp = chunks.map((c) => `${c.id}:${c.revision}:${c.status}`).join("|");
  useEffect(() => {
    if (project.status !== "editing") { setLines([]); return; }
    editor.listOverlaps(project.id).then(setLines).catch(() => setLines([]));
  }, [project.id, project.status, stamp]);

  if (busy === null && lines.length === 0 && !note) return null;

  async function fix(mode) {
    const what = mode === "speed"
      ? "speed each overlapping line up just enough to end before the next one (up to 2×)"
      : "ask Gemini to shorten each overlapping line's wording, keeping its meaning, and re-voice it";
    if (!window.confirm(`Fix ${lines.length} overlap${lines.length > 1 ? "s" : ""}: ${what}?`)) return;
    setBusy(mode); setNote(null);
    try {
      const r = await editor.fixOverlaps(project.id, mode);
      const n = r.fixed.length, k = r.skipped.length;
      setNote({ kind: k ? "err" : "ok",
                text: `${n} line${n !== 1 ? "s" : ""} ${mode === "speed" ? "sped up" : "shortened"}; re-voicing now.`
                  + (k ? ` ${k} couldn't be fixed this way (${r.skipped[0].reason}). Try the other option, or edit it.` : "") });
    } catch (e) {
      setNote({ kind: "err", text: e.message });
    }
    setBusy(null);
  }

  return (
    <div className={`ovl ${compact ? "ovl-compact" : ""}`} role="status">
      {lines.length > 0 && (
        <>
          <span className="ovl-text">
            ⚠ {lines.length} line{lines.length > 1 ? "s run" : " runs"} into the next one.
            {!compact && " Fix by:"}
          </span>
          <button className="btn btn-quiet btn-xs" onClick={() => fix("speed")} disabled={!!busy}
                  title="Exactly the speed each line needs to end in time (max 2×)">
            {busy === "speed" ? <><Loader size={12} /> Speeding up…</> : "Speed up to fit"}
          </button>
          <button className="btn btn-quiet btn-xs" onClick={() => fix("shorten")} disabled={!!busy}
                  title="Gemini rewrites the line shorter, keeping its meaning">
            {busy === "shorten" ? <><Loader size={12} /> Shortening…</> : "Shorten the text"}
          </button>
        </>
      )}
      {note && <span className={`ovl-note ovl-${note.kind}`}>{note.text}
        <button className="ovl-x" onClick={() => setNote(null)} aria-label="Dismiss">×</button></span>}
    </div>
  );
}
