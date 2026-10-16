// App-wide toasts: transient messages that fade out on their own (errors stay longer) and can be
// dismissed. Use for outcomes of an action ("Couldn't delete: …"); keep inline banners for state
// that persists (a failed project, a missing service).
import { useSyncExternalStore } from "react";
import { AnimatePresence, motion } from "framer-motion";

const LIFETIME_MS = { info: 4000, success: 3000, error: 8000 };
let items = [];
const listeners = new Set();
const emit = () => listeners.forEach((l) => l());

export function toast(message, kind = "info") {
  const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  items = [...items.slice(-3), { id, message, kind }];      // at most four at once
  emit();
  setTimeout(() => dismiss(id), LIFETIME_MS[kind] ?? 4000);
  return id;
}
toast.error = (m) => toast(m, "error");
toast.success = (m) => toast(m, "success");

export function dismiss(id) {
  items = items.filter((t) => t.id !== id);
  emit();
}

export function Toaster() {
  const list = useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => items);
  return (
    <div className="toaster" aria-live="polite" aria-atomic="false">
      <AnimatePresence initial={false}>
        {list.map((t) => (
          <motion.div key={t.id} layout className={`toast toast-${t.kind}`} role={t.kind === "error" ? "alert" : "status"}
                      initial={{ opacity: 0, y: 12, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: 8, scale: 0.98 }} transition={{ duration: 0.18 }}>
            <span className="toast-dot" aria-hidden="true" />
            <span className="toast-msg">{t.message}</span>
            <button className="toast-x" onClick={() => dismiss(t.id)} aria-label="Dismiss">×</button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
