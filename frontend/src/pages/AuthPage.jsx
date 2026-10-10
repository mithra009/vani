import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { useAuth } from "../lib/auth.jsx";
import { authApi } from "../lib/api.js";
import { Logo } from "../components/Icons.jsx";

const USERNAME_RE = /^[a-z0-9][a-z0-9_-]{1,28}[a-z0-9]$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function Field({ id, label, error, hint, children }) {
  return (
    <div className="auth-field">
      <label htmlFor={id} className="field-label">{label}</label>
      {children}
      {error ? <p className="auth-err" id={`${id}-err`} role="alert">{error}</p>
        : hint ? <p className="auth-hint" id={`${id}-hint`}>{hint}</p> : null}
    </div>
  );
}

export default function AuthPage() {
  const { signIn, signUp, configured } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [tab, setTab] = useState(loc.pathname === "/signup" ? "signup" : "signin");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [showPw, setShowPw] = useState(false);

  const [f, setF] = useState({ username: "", first_name: "", last_name: "", email: "", password: "", identifier: "" });
  const [touched, setTouched] = useState({});
  const [userCheck, setUserCheck] = useState(null);   // null | checking | available | taken
  const checkT = useRef(null);

  const set = (k) => (e) => setF((x) => ({ ...x, [k]: k === "username" ? e.target.value.toLowerCase() : e.target.value }));
  const touch = (k) => () => setTouched((t) => ({ ...t, [k]: true }));
  const dest = loc.state?.from || "/";

  useEffect(() => { setError(null); setTouched({}); }, [tab]);

  useEffect(() => {
    if (tab !== "signup" || !USERNAME_RE.test(f.username)) { setUserCheck(null); return; }
    setUserCheck("checking");
    clearTimeout(checkT.current);
    checkT.current = setTimeout(async () => {
      try {
        const r = await authApi.usernameAvailable(f.username);
        setUserCheck(r.available ? "available" : "taken");
      } catch { setUserCheck(null); }
    }, 350);
    return () => clearTimeout(checkT.current);
  }, [f.username, tab]);

  const errs = tab === "signup" ? {
    username: !f.username ? "Choose a username."
      : !USERNAME_RE.test(f.username) ? "3–30 characters: lowercase letters, numbers, - or _. Start and end with a letter or number."
      : userCheck === "taken" ? "That username is taken." : null,
    first_name: !f.first_name.trim() ? "Enter your first name." : null,
    last_name: !f.last_name.trim() ? "Enter your last name." : null,
    email: !f.email ? "Enter your email." : !EMAIL_RE.test(f.email) ? "Enter a valid email address." : null,
    password: !f.password ? "Create a password." : f.password.length < 8 ? "Use at least 8 characters." : null,
  } : {
    identifier: !f.identifier.trim() ? "Enter your username or email." : null,
    password: !f.password ? "Enter your password." : null,
  };
  const valid = Object.values(errs).every((e) => !e) && !(tab === "signup" && userCheck === "checking");
  const show = (k) => (touched[k] || touched._submit) && errs[k];

  async function submit(e) {
    e.preventDefault();
    setTouched((t) => ({ ...t, _submit: true }));
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      if (tab === "signup") {
        await signUp({ username: f.username, first_name: f.first_name.trim(), last_name: f.last_name.trim(),
                       email: f.email.trim(), password: f.password });
      } else {
        await signIn(f.identifier.trim(), f.password);
      }
      nav(dest, { replace: true });
    } catch (err) {
      setError(err.message === "Failed to fetch" ? "Can't reach the server. Check it's running and try again." : err.message);
      setBusy(false);
    }
  }

  const pwInput = (autoComplete) => (
    <div className="pw-wrap">
      <input id="password" className="input" type={showPw ? "text" : "password"} value={f.password}
             onChange={set("password")} onBlur={touch("password")} autoComplete={autoComplete}
             aria-invalid={!!show("password")} aria-describedby={show("password") ? "password-err" : undefined} />
      <button type="button" className="pw-toggle" onClick={() => setShowPw((s) => !s)}
              aria-label={showPw ? "Hide password" : "Show password"}>{showPw ? "Hide" : "Show"}</button>
    </div>
  );

  return (
    <div className="auth-page">
      <motion.div className="auth-card" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
        <div className="auth-logo"><Logo /></div>
        <h1 className="auth-title">{tab === "signup" ? "Create your Vani account" : "Sign in to Vani"}</h1>
        <p className="auth-sub">
          {tab === "signup" ? "One account for all your dubbing and narration projects." : "Use your username or email."}
        </p>

        <div className="seg-control auth-tabs" role="tablist" aria-label="Account">
          <button role="tab" aria-selected={tab === "signin"} aria-pressed={tab === "signin"} onClick={() => setTab("signin")}>Sign in</button>
          <button role="tab" aria-selected={tab === "signup"} aria-pressed={tab === "signup"} onClick={() => setTab("signup")}>Create account</button>
        </div>

        {!configured && (
          <div className="banner error" role="alert"><span className="banner-dot" />
            <span>Sign-in isn't configured. Add SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY to .env and restart the frontend.</span>
          </div>
        )}

        <form onSubmit={submit} noValidate>
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={tab} className="auth-fields"
                        initial={{ opacity: 0, x: tab === "signup" ? 12 : -12 }} animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0 }} transition={{ duration: 0.2 }}>
              {tab === "signup" ? (
                <>
                  <Field id="username" label="Username" error={show("username")}
                         hint={userCheck === "available" ? "✓ Available" : userCheck === "checking" ? "Checking…" : "Lowercase letters, numbers, - and _"}>
                    <div className="prefix-wrap">
                      <span className="prefix" aria-hidden="true">@</span>
                      <input id="username" className="input input-prefixed" value={f.username} onChange={set("username")}
                             onBlur={touch("username")} autoComplete="username" autoCapitalize="none" spellCheck={false}
                             maxLength={30} aria-invalid={!!show("username")} />
                    </div>
                  </Field>
                  <div className="auth-row">
                    <Field id="first_name" label="First name" error={show("first_name")}>
                      <input id="first_name" className="input" value={f.first_name} onChange={set("first_name")}
                             onBlur={touch("first_name")} autoComplete="given-name" maxLength={60} aria-invalid={!!show("first_name")} />
                    </Field>
                    <Field id="last_name" label="Last name" error={show("last_name")}>
                      <input id="last_name" className="input" value={f.last_name} onChange={set("last_name")}
                             onBlur={touch("last_name")} autoComplete="family-name" maxLength={60} aria-invalid={!!show("last_name")} />
                    </Field>
                  </div>
                  <Field id="email" label="Email" error={show("email")}>
                    <input id="email" className="input" type="email" value={f.email} onChange={set("email")}
                           onBlur={touch("email")} autoComplete="email" aria-invalid={!!show("email")} />
                  </Field>
                  <Field id="password" label="Password" error={show("password")} hint="At least 8 characters">
                    {pwInput("new-password")}
                  </Field>
                </>
              ) : (
                <>
                  <Field id="identifier" label="Username or email" error={show("identifier")}>
                    <input id="identifier" className="input" value={f.identifier} onChange={set("identifier")}
                           onBlur={touch("identifier")} autoComplete="username" autoCapitalize="none" spellCheck={false}
                           aria-invalid={!!show("identifier")} />
                  </Field>
                  <Field id="password" label="Password" error={show("password")}>
                    {pwInput("current-password")}
                  </Field>
                </>
              )}
            </motion.div>
          </AnimatePresence>

          {error && <div className="banner error" role="alert" style={{ marginTop: 18 }}><span className="banner-dot" /><span>{error}</span></div>}

          <button type="submit" className="btn btn-primary auth-submit" disabled={busy || !configured}>
            {busy ? (tab === "signup" ? "Creating account…" : "Signing in…") : tab === "signup" ? "Create account" : "Sign in"}
          </button>
        </form>

        <p className="auth-switch">
          {tab === "signup" ? "Already have an account? " : "New to Vani? "}
          <button className="link-btn" onClick={() => setTab(tab === "signup" ? "signin" : "signup")}>
            {tab === "signup" ? "Sign in" : "Create one"}
          </button>
        </p>
      </motion.div>
    </div>
  );
}
