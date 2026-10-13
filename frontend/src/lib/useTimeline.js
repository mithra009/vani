// Timeline state for one project: instant local apply, undo/redo, autosave (design §10.3).
//
// - Every edit applies locally at once and is queued; ~1 s after the last edit (and on page
//   hide) the queue is sent as {base_version, ops}.
// - 409: rebase the unsaved ops onto the server's doc; ops that no longer apply are dropped and
//   reported, never silently.
// - Unsaved ops survive a reload via localStorage. Undo history is session-only (C9-proposal).
import { useCallback, useEffect, useRef, useState } from "react";
import * as editor from "./editorApi.js";
import { apply, OpError } from "./timeline.js";

const SAVE_DELAY_MS = 1000;
const RETRY_MS = 4000;
const storeKey = (pid) => `vani.timeline.unsaved.${pid}`;

function loadUnsaved(pid) {
  try { return JSON.parse(localStorage.getItem(storeKey(pid)) || "null"); } catch { return null; }
}
function storeUnsaved(pid, value) {
  try {
    if (value?.ops?.length) localStorage.setItem(storeKey(pid), JSON.stringify(value));
    else localStorage.removeItem(storeKey(pid));
  } catch { /* storage unavailable: the in-memory queue still saves */ }
}

/** ctx: { sourceS, chunkIds:Set, media:{id: seconds} } — references the server would check. */
export function useTimeline(projectId, ctx) {
  const [state, setState] = useState({ status: "loading", doc: null, version: 0, error: null });
  const [save, setSave] = useState({ state: "saved", message: null });     // saved | saving | retrying | error
  const [notices, setNotices] = useState([]);
  const base = useRef({ doc: null, version: 0 });     // last server-confirmed doc
  const pending = useRef([]);                          // ops applied locally, not yet saved
  const undo = useRef([]);
  const redo = useRef([]);
  const timer = useRef(null);
  const inflight = useRef(false);
  const ctxRef = useRef(ctx);
  ctxRef.current = ctx;
  const [, bump] = useState(0);

  const notify = useCallback((msg) => setNotices((n) => [...n.slice(-4), { id: Date.now() + Math.random(), msg }]), []);

  const replay = useCallback((doc, ops) => {
    const kept = [], dropped = [];
    for (const op of ops) {
      try { [doc] = apply(doc, op, ctxRef.current); kept.push(op); }
      catch (e) { dropped.push(`${op.type}: ${e.message}`); }
    }
    return { doc, kept, dropped };
  }, []);

  // Load + restore unsaved ops from a previous session.
  useEffect(() => {
    let cancelled = false;
    editor.getTimeline(projectId).then((tl) => {
      if (cancelled) return;
      base.current = { doc: tl.doc, version: tl.version };
      const saved = loadUnsaved(projectId);
      let doc = tl.doc;
      if (saved?.ops?.length) {
        const r = replay(tl.doc, saved.ops);
        doc = r.doc;
        pending.current = r.kept;
        if (r.dropped.length) notify(`${r.dropped.length} unsaved edit(s) from last time no longer apply and were dropped.`);
        if (r.kept.length) schedule(0);
      }
      setState({ status: "ready", doc, version: tl.version, error: null });
    }).catch((e) => !cancelled && setState({ status: "error", doc: null, version: 0, error: e.message }));
    return () => { cancelled = true; clearTimeout(timer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const flush = useCallback(async () => {
    if (inflight.current || !pending.current.length) return;
    inflight.current = true;
    const batch = pending.current.slice();
    setSave({ state: "saving", message: null });
    try {
      const res = await editor.saveOps(projectId, base.current.version, batch);
      base.current = { doc: res.doc, version: res.version };
      pending.current = pending.current.slice(batch.length);
      storeUnsaved(projectId, { ops: pending.current });
      setSave({ state: pending.current.length ? "saving" : "saved", message: null });
      setState((s) => ({ ...s, version: res.version }));
    } catch (e) {
      if (e.status === 409 && e.current) {
        // Another tab saved first: rebase everything unsaved onto the server's doc.
        base.current = e.current;
        const r = replay(e.current.doc, pending.current);
        pending.current = r.kept;
        storeUnsaved(projectId, { ops: r.kept });
        if (r.dropped.length) notify(`The timeline changed elsewhere; ${r.dropped.length} of your edits no longer apply: ${r.dropped.join("; ")}`);
        setState((s) => ({ ...s, doc: r.doc, version: e.current.version }));
        undo.current = []; redo.current = [];        // inverses were computed against the old doc
        setSave({ state: "saving", message: null });
        inflight.current = false;
        return flush();
      }
      if (e.status === 422) {
        // The server rejected an op the browser accepted: the two rule sets disagree. Roll back.
        pending.current = [];
        storeUnsaved(projectId, null);
        setState((s) => ({ ...s, doc: base.current.doc, version: base.current.version }));
        undo.current = []; redo.current = [];
        setSave({ state: "error", message: `Edit rejected by the server and undone: ${e.message}` });
      } else {
        setSave({ state: "retrying", message: `Not saved: ${e.message}. Retrying…` });
        clearTimeout(timer.current);
        timer.current = setTimeout(() => flush(), RETRY_MS);
      }
    } finally {
      inflight.current = false;
    }
    if (pending.current.length) schedule(SAVE_DELAY_MS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  function schedule(ms) {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => flush(), ms);
  }

  useEffect(() => {
    const hide = () => { if (document.visibilityState === "hidden") flush(); };
    document.addEventListener("visibilitychange", hide);
    return () => document.removeEventListener("visibilitychange", hide);
  }, [flush]);

  /** Apply ops locally. Throws OpError (the caller shows it) — nothing is half-applied. */
  const run = useCallback((ops, { record = true } = {}) => {
    let doc = state.doc;
    const invs = [];
    for (const op of ops) { let inv; [doc, inv] = apply(doc, op, ctxRef.current); invs.push(inv); }
    if (record) { undo.current.push({ ops, invs }); redo.current = []; }
    pending.current = [...pending.current, ...ops];
    storeUnsaved(projectId, { ops: pending.current });
    setState((s) => ({ ...s, doc }));
    setSave({ state: "saving", message: null });
    schedule(SAVE_DELAY_MS);
    bump((x) => x + 1);
    return doc;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.doc, projectId]);

  const tryRun = useCallback((ops) => {
    try { run(ops); return true; }
    catch (e) { if (e instanceof OpError) { notify(e.message); return false; } throw e; }
  }, [run, notify]);

  const doUndo = useCallback(() => {
    const step = undo.current.pop();
    if (!step) return;
    try { run([...step.invs].reverse(), { record: false }); redo.current.push(step); }
    catch (e) { notify(`Can't undo: ${e.message}`); }
  }, [run, notify]);

  const doRedo = useCallback(() => {
    const step = redo.current.pop();
    if (!step) return;
    try { run(step.ops, { record: false }); undo.current.push(step); }
    catch (e) { notify(`Can't redo: ${e.message}`); }
  }, [run, notify]);

  return {
    ...state, save, notices, dismiss: (id) => setNotices((n) => n.filter((x) => x.id !== id)),
    run: tryRun, undo: doUndo, redo: doRedo,
    canUndo: undo.current.length > 0, canRedo: redo.current.length > 0, flush,
  };
}
