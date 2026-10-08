import { useEffect, useState } from "react";
import { NavLink, Link, Route, Routes } from "react-router-dom";
import { initApi } from "./lib/api.js";
import { Logo } from "./components/Icons.jsx";
import Home from "./pages/Home.jsx";
import Projects from "./pages/Projects.jsx";
import Job from "./pages/Job.jsx";

export default function App() {
  const [mode, setMode] = useState(null);

  useEffect(() => { initApi().then(setMode); }, []);

  return (
    <>
      <header className="nav">
        <nav className="nav-inner" aria-label="Main">
          <Link to="/" className="logo"><Logo />Vani</Link>
          <div className="nav-links">
            <NavLink to="/" end>New dub</NavLink>
            <NavLink to="/projects">Projects</NavLink>
          </div>
          {mode && (
            <span className={`mode-pill ${mode === "live" ? "live" : ""}`}
                  title={mode === "live" ? "Connected to the backend" : "Backend not running: simulated pipeline with sample data"}>
              {mode === "live" ? "Live" : "Demo mode"}
            </span>
          )}
        </nav>
      </header>

      <main>
        {mode ? (
          <Routes>
            <Route path="/" element={<Home mode={mode} />} />
            <Route path="/projects" element={<Projects />} />
            <Route path="/jobs/:id" element={<Job mode={mode} />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        ) : (
          <div className="progress-wrap"><div className="spinner" style={{ margin: "0 auto" }} /></div>
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

function NotFound() {
  return (
    <div className="page empty">
      <h1 className="title">Page not found</h1>
      <Link to="/">Start a new dub</Link>
    </div>
  );
}
