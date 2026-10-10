import { useEffect, useRef, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { initApi } from "./lib/api.js";
import { AuthProvider, useAuth } from "./lib/auth.jsx";
import { Logo } from "./components/Icons.jsx";
import Landing from "./pages/Landing.jsx";
import NewProject from "./pages/NewProject.jsx";
import Library from "./pages/Library.jsx";
import Projects from "./pages/Projects.jsx";
import Job from "./pages/Job.jsx";
import AuthPage from "./pages/AuthPage.jsx";

export default function App() {
  const [mode, setMode] = useState(null);
  useEffect(() => { initApi().then(setMode); }, []);

  return (
    <AuthProvider>
      <Shell mode={mode} />
    </AuthProvider>
  );
}

function Shell({ mode }) {
  const { status } = useAuth();
  // Demo mode (no backend) needs no account; live mode requires signing in.
  const gated = mode === "live";
  const ready = mode && (!gated || status !== "loading");
  const signedIn = !gated || status === "signed_in";

  return (
    <>
      <header className="nav">
        <nav className="nav-inner" aria-label="Main">
          <Link to="/" className="logo"><Logo />Vani</Link>
          {signedIn && (
            <div className="nav-links">
              <NavLink to="/" end>Home</NavLink>
              <NavLink to="/library">Library</NavLink>
              <NavLink to="/projects">Projects</NavLink>
              <Link to="/new" className="nav-cta">New project</Link>
            </div>
          )}
          {mode && (
            <span className={`mode-pill ${mode === "live" ? "live" : ""}`} style={signedIn ? undefined : { marginLeft: "auto" }}
                  title={mode === "live" ? "Connected to the backend" : "Backend not running: simulated pipeline with sample data"}>
              {mode === "live" ? "Live" : "Demo mode"}
            </span>
          )}
          {gated && status === "signed_in" && <UserMenu />}
        </nav>
      </header>

      <main>
        {!ready ? (
          <div className="progress-wrap"><div className="spinner" style={{ margin: "0 auto" }} /></div>
        ) : (
          <Routes>
            <Route path="/signin" element={signedIn && gated ? <Navigate to="/" replace /> : <AuthPage />} />
            <Route path="/signup" element={signedIn && gated ? <Navigate to="/" replace /> : <AuthPage />} />
            <Route path="/" element={<Protected ok={signedIn}><Landing mode={mode} /></Protected>} />
            <Route path="/new" element={<Protected ok={signedIn}><NewProject mode={mode} /></Protected>} />
            <Route path="/library" element={<Protected ok={signedIn}><Library /></Protected>} />
            <Route path="/projects" element={<Protected ok={signedIn}><Projects /></Protected>} />
            <Route path="/jobs/:id" element={<Protected ok={signedIn}><Job mode={mode} /></Protected>} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        )}
      </main>

      <footer className="footer">
        <div className="footer-inner">
          <span>Speech by Gnani Prisma v2.5 and Timbre v2.5. Translation by Gemini 3.5 Flash-Lite.</span>
          <span>Only dub videos you own. Only clone voices with consent.</span>
        </div>
      </footer>
    </>
  );
}

function Protected({ ok, children }) {
  const loc = useLocation();
  return ok ? children : <Navigate to="/signin" replace state={{ from: loc.pathname }} />;
}

const PASTELS = [
  ["#c9b8f0", "#211a3a"],   // lavender
  ["#a8e6cf", "#0f2a20"],   // mint
  ["#f5c99e", "#3a2412"],   // peach
  ["#f2b5c4", "#3a1621"],   // rose
  ["#b8d8f5", "#10233a"],   // sky
  ["#f0e3a1", "#332b0c"],   // butter
];
const pastelFor = (key = "") => PASTELS[[...key].reduce((a, c) => a + c.charCodeAt(0), 0) % PASTELS.length];

const I = {
  projects: <path d="M4 7.5A2.5 2.5 0 0 1 6.5 5h3.2l1.6 1.8h6.2A2.5 2.5 0 0 1 20 9.3v7.2a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 16.5z" />,
  library: <><rect x="4" y="5" width="16" height="14" rx="2.5" /><path d="M10.5 9.5v5l4-2.5z" /></>,
  plus: <path d="M12 6v12M6 12h12" />,
  signout: <><path d="M14 5h3.5A1.5 1.5 0 0 1 19 6.5v11a1.5 1.5 0 0 1-1.5 1.5H14" /><path d="M10 8l-4 4 4 4M6 12h9" /></>,
};
const Ico = ({ d }) => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
);

function UserMenu() {
  const { profile, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const menuRef = useRef(null);
  const nav = useNavigate();

  useEffect(() => {
    if (!open) return;
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    const keys = (e) => {
      if (e.key === "Escape") { setOpen(false); ref.current?.querySelector(".avatar-btn")?.focus(); return; }
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      e.preventDefault();
      const items = [...(menuRef.current?.querySelectorAll('[role="menuitem"]') || [])];
      const i = items.indexOf(document.activeElement);
      const next = e.key === "ArrowDown" ? (i + 1) % items.length : (i - 1 + items.length) % items.length;
      items[next]?.focus();
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", keys);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", keys); };
  }, [open]);

  if (!profile) return null;
  const initials = `${profile.first_name?.[0] || ""}${profile.last_name?.[0] || ""}`.toUpperCase();
  const [bg, fg] = pastelFor(profile.username);
  const go = (path) => { setOpen(false); nav(path); };

  return (
    <div className="user-menu" ref={ref}>
      <button className="avatar-btn" style={{ background: bg, color: fg }} onClick={() => setOpen((o) => !o)}
              aria-haspopup="menu" aria-expanded={open} aria-label={`Account: ${profile.first_name} ${profile.last_name}`}>
        {initials}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div ref={menuRef} className="acct-menu" role="menu" aria-label="Account"
                      initial={{ opacity: 0, scale: 0.96, y: -6 }} animate={{ opacity: 1, scale: 1, y: 0 }}
                      exit={{ opacity: 0, scale: 0.97, y: -4 }} transition={{ duration: 0.16, ease: [0.28, 0.11, 0.32, 1] }}>
            <div className="acct-head">
              <span className="acct-avatar" style={{ background: bg, color: fg }} aria-hidden="true">{initials}</span>
              <div className="acct-id">
                <span className="acct-name">{profile.first_name} {profile.last_name}</span>
                <span className="acct-user">@{profile.username}</span>
                <span className="acct-email" title={profile.email}>{profile.email}</span>
              </div>
            </div>
            <div className="acct-group">
              <button className="acct-item" role="menuitem" onClick={() => go("/projects")}><Ico d={I.projects} />Your projects</button>
              <button className="acct-item" role="menuitem" onClick={() => go("/library")}><Ico d={I.library} />Library</button>
              <button className="acct-item" role="menuitem" onClick={() => go("/new")}><Ico d={I.plus} />New project</button>
            </div>
            <div className="acct-group">
              <button className="acct-item acct-signout" role="menuitem"
                      onClick={async () => { setOpen(false); await signOut(); nav("/signin"); }}>
                <Ico d={I.signout} />Sign out
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function NotFound() {
  return (
    <div className="page empty">
      <h1 className="title">Page not found</h1>
      <Link to="/">Go home</Link>
    </div>
  );
}
