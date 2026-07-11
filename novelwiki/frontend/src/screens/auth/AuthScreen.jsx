/* ============================================================
   Auth — login / register / forgot / reset / verify with a brand panel.
   Routes: /login /register /forgot /reset?token= /verify?token= /verify-failed
   ============================================================ */
import React, { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { API } from "../../lib/api.js";
import { Icon } from "../../components/Icon.jsx";
import { Button } from "../../components/ui.jsx";
import { useTitle } from "../../lib/hooks.js";

const MODE_BY_PATH = {
  "/login": "login", "/register": "register", "/forgot": "forgot",
  "/reset": "reset", "/verify": "verify", "/verify-failed": "verify-failed",
};

function PasswordInput({ value, onChange, placeholder, autoComplete, id }) {
  const [show, setShow] = useState(false);
  return (
    <div className="pw-wrap">
      <input id={id} type={show ? "text" : "password"} value={value} placeholder={placeholder}
             autoComplete={autoComplete} onChange={e => onChange(e.target.value)} />
      <button type="button" className="pw-toggle" aria-label={show ? "Hide password" : "Show password"}
              onClick={() => setShow(s => !s)} tabIndex={-1}>
        <Icon name={show ? "eyeOff" : "eye"} size={16} />
      </button>
    </div>
  );
}

const USERNAME_RE = /^[a-z0-9_]{3,24}$/;

export function AuthScreen({ onAuthed }) {
  const location = useLocation();
  const navigate = useNavigate();
  const params = new URLSearchParams(location.search);
  const mode = MODE_BY_PATH[location.pathname] || "login";
  const token = params.get("token") || "";

  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [providers, setProviders] = useState([]);
  const [error, setError] = useState(params.get("error") === "oauth" ? "Sign-in with that provider failed." : "");
  const [info, setInfo] = useState(
    mode === "verify" ? "Confirm your email to finish verification."
    : mode === "verify-failed" ? "That verification link is invalid or expired." : ""
  );
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState({});

  useTitle(mode === "register" ? "Create account" : mode === "login" ? "Sign in" : "Account");

  useEffect(() => {
    API.auth.providers().then(r => setProviders(r.providers || [])).catch(() => {});
  }, []);
  useEffect(() => { setError(""); }, [location.pathname]);

  // Field-level validation (register only; login stays forgiving).
  const fieldErrors = useMemo(() => {
    const errs = {};
    if (mode === "register") {
      if (touched.email && email && !/^\S+@\S+\.\S+$/.test(email.trim())) errs.email = "That doesn't look like an email address.";
      if (touched.username && username && !USERNAME_RE.test(username.trim().toLowerCase())) errs.username = "3–24 characters: a–z, 0–9, underscore.";
      if (touched.password && password && password.length < 8) errs.password = "At least 8 characters.";
    }
    if (mode === "reset" && touched.password && password && password.length < 8) errs.password = "At least 8 characters.";
    return errs;
  }, [mode, email, username, password, touched]);

  const go = (path) => { setError(""); navigate(path); };

  async function submit(e) {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      if (mode === "login") {
        const user = await API.auth.login(identifier.trim(), password);
        onAuthed(user);
      } else if (mode === "register") {
        const user = await API.auth.register(email.trim(), username.trim(), password);
        onAuthed(user);
      } else if (mode === "forgot") {
        await API.auth.requestReset(email.trim());
        setInfo("If that email has an account, a reset link is on its way.");
        navigate("/login");
      } else if (mode === "reset") {
        await API.auth.reset(token, password);
        setInfo("Password updated — please sign in.");
        navigate("/login");
      } else if (mode === "verify") {
        await API.auth.verify(token);
        try {
          const user = await API.auth.me();
          onAuthed(user);
        } catch (e2) {
          setInfo("Email verified — you can sign in.");
          navigate("/login");
        }
      }
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const title = mode === "reset" ? "Set a new password"
    : mode === "forgot" ? "Reset your password"
    : mode === "verify" ? "Verify your email"
    : mode === "verify-failed" ? "Verification failed"
    : mode === "register" ? "Create your account" : "Welcome back";

  const submitLabel = mode === "reset" ? "Update password"
    : mode === "forgot" ? "Send reset link"
    : mode === "verify" ? "Verify email"
    : mode === "register" ? "Create account" : "Sign in";

  const OAUTH_NAMES = { google: "Google", discord: "Discord" };

  return (
    <div className="auth-split">
      <div className="auth-brandpane">
        <div className="auth-brand-row">
          <span className="brand-mark" aria-hidden>T</span>
        </div>
        <div>
          <h1 className="auth-wordmark">Tideglass</h1>
          <p className="auth-promise">Your novels — translated, narrated, spoiler-safe. Pick up any story exactly where the tide left it.</p>
        </div>
        <div />
      </div>
      <div className="auth-formpane">
        <form className="auth-card page-enter" onSubmit={submit}>
          <h2 className="auth-title">{title}</h2>
          {info && <div className="auth-info">{info}</div>}
          {error && <div className="auth-error" role="alert">{error}</div>}

          {mode === "register" && (
            <>
              <label className={"field" + (fieldErrors.email ? " has-error" : "")}>
                <span>Email</span>
                <input type="email" value={email} placeholder="you@example.com" autoComplete="email"
                       onChange={e => setEmail(e.target.value)} onBlur={() => setTouched(t => ({ ...t, email: true }))} />
                {fieldErrors.email && <span className="field-error">{fieldErrors.email}</span>}
              </label>
              <label className={"field" + (fieldErrors.username ? " has-error" : "")}>
                <span>Username</span>
                <input value={username} placeholder="a–z, 0–9, underscore" autoComplete="username"
                       onChange={e => setUsername(e.target.value)} onBlur={() => setTouched(t => ({ ...t, username: true }))} />
                {fieldErrors.username && <span className="field-error">{fieldErrors.username}</span>}
              </label>
              <label className={"field" + (fieldErrors.password ? " has-error" : "")}>
                <span>Password</span>
                <PasswordInput value={password} onChange={(v) => { setPassword(v); setTouched(t => ({ ...t, password: true })); }}
                               placeholder="at least 8 characters" autoComplete="new-password" />
                {fieldErrors.password
                  ? <span className="field-error">{fieldErrors.password}</span>
                  : password.length >= 8 && <span className="field-help">Looks good.</span>}
              </label>
            </>
          )}

          {mode === "login" && (
            <>
              <label className="field">
                <span>Email or username</span>
                <input value={identifier} autoComplete="username" onChange={e => setIdentifier(e.target.value)} />
              </label>
              <label className="field">
                <span>Password</span>
                <PasswordInput value={password} onChange={setPassword} autoComplete="current-password" />
              </label>
            </>
          )}

          {mode === "forgot" && (
            <label className="field">
              <span>Email</span>
              <input type="email" value={email} placeholder="you@example.com" autoComplete="email"
                     onChange={e => setEmail(e.target.value)} />
            </label>
          )}

          {mode === "reset" && (
            <label className={"field" + (fieldErrors.password ? " has-error" : "")}>
              <span>New password</span>
              <PasswordInput value={password} onChange={(v) => { setPassword(v); setTouched(t => ({ ...t, password: true })); }}
                             placeholder="at least 8 characters" autoComplete="new-password" />
              {fieldErrors.password && <span className="field-error">{fieldErrors.password}</span>}
            </label>
          )}

          {mode !== "verify-failed" && (
            <Button type="submit" variant="primary" full size="lg" loading={busy}
                    disabled={busy || (mode === "verify" && !token)}>
              {submitLabel}
            </Button>
          )}

          {(mode === "login" || mode === "register") && providers.length > 0 && (
            <>
              <div className="auth-divider"><span>or continue with</span></div>
              {providers.map(p => (
                <Button key={p} variant="ghost" full onClick={() => API.auth.oauthStart(p)} icon="external">
                  {OAUTH_NAMES[p] || p}
                </Button>
              ))}
            </>
          )}

          <div className="auth-links">
            {mode === "login" && (
              <>
                <button type="button" className="auth-linkbtn" onClick={() => go("/forgot")}>Forgot password?</button>
                <button type="button" className="auth-linkbtn" onClick={() => go("/register")}>Create an account</button>
              </>
            )}
            {mode !== "login" && (
              <button type="button" className="auth-linkbtn" onClick={() => go("/login")}>← Back to sign in</button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
