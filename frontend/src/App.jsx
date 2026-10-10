import { useEffect, useRef, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { initApi } from "./lib/api.js";
import { AuthProvider, useAuth } from "./lib/auth.jsx";
import { Logo } from "./components/Icons.jsx";
import Home from "./pages/Home.jsx";
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
              <NavLink to="/" end>New dub</NavLink>
              <NavLink to="/projects">Projects</NavLink>
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
            <Route path="/" element={<Protected ok={signedIn}><Home mode={mode} /></Protected>} />
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

function UserMenu() {
  const { profile, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const nav = useNavigate();

  useEffect(() => {
    if (!open) return;
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    const esc = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);

  if (!profile) return null;
  const initials = `${profile.first_name?.[0] || ""}${profile.last_name?.[0] || ""}`.toUpperCase();

  return (
    <div className="user-menu" ref={ref}>
      <button className="avatar-btn" onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open}
              aria-label={`Account: ${profile.first_name} ${profile.last_name}`}>{initials}</button>
      {open && (
        <div className="menu" role="menu">
          <div className="menu-head">
            <div className="menu-name">{profile.first_name} {profile.last_name}</div>
            <div className="menu-sub">@{profile.username}</div>
            <div className="menu-sub">{profile.email}</div>
          </div>
          <button className="menu-item" role="menuitem" onClick={() => { setOpen(false); nav("/projects"); }}>Your projects</button>
          <button className="menu-item" role="menuitem" onClick={async () => { setOpen(false); await signOut(); nav("/signin"); }}>Sign out</button>
        </div>
      )}
    </div>
  );
}

function NotFound() {
  return (
    <div className="page empty">
      <h1 className="title">Page not found</h1>
      <Link to="/">Start a new dub</Link>
    </div>
  );
}
