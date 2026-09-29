/* ============================================================
   Auth — sign in, register and recovery, on a moonlit sea.
   Routes: /login /register /forgot /reset?token= /verify?token= /verify-failed

   The stage: a real-time WebGL ocean (atmosphere/OceanScene) — night in
   Tide, dawn in Pearl. "Tideglass" rises letter by letter out of the
   waterline with a rippling reflection, a line of promise follows, and the
   form floats in on a frosted sea-glass card. Switching modes keeps the sea
   rolling (the route change is not cross-faded, see auth.css): the card
   morphs to the new height on a spring while its content cross-fades.
   ============================================================ */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { authApi } from "./api.js";
import { Icon } from "../../components/Icon.jsx";
import { Button } from "../../components/ui.jsx";
import { useTitle } from "../../lib/hooks.js";
import { AnimatePresence, animate, ease, motion, springs, useMotionValue, useReducedMotion } from "../../motion/index.js";
import { OceanScene } from "../../atmosphere/OceanScene.jsx";
import {
  AuthBrandMark, AuthNotice, FieldNote, Glyph, MorphHeight, PasswordInput, PresenceForm, ProviderButton,
  ThemeSwitch, Wordmark, useFontReady,
} from "./AuthParts.jsx";

const MODE_BY_PATH = {
  "/login": "login", "/register": "register", "/forgot": "forgot",
  "/reset": "reset", "/verify": "verify", "/verify-failed": "verify-failed",
};

const USERNAME_RE = /^[a-z0-9_]{3,24}$/;

const TITLES = {
  reset: "Set a new password", forgot: "Reset your password", verify: "Verify your email",
  "verify-failed": "Verification failed", register: "Create your account", login: "Welcome back",
};
const SUBMIT_LABELS = {
  reset: "Update password", forgot: "Send reset link", verify: "Verify email",
  register: "Create account", login: "Sign in",
};
const LEDES = {
  login: "Pick up every story right where the tide left it.",
  register: "A library that translates, narrates and never spoils.",
  forgot: "Enter your account email and we’ll send you a reset link.",
  reset: "Choose a new password of at least 8 characters.",
};

/* The form cross-fades between modes: the old one lifts away into a blur
   while the new one's rows rise in, staggered. */
const formVariants = {
  hidden: {},
  show: (delay) => ({ transition: { staggerChildren: 0.05, delayChildren: delay } }),
  exit: { opacity: 0, y: -10, filter: "blur(6px)", transition: { duration: 0.16, ease: ease.in } },
};
const itemVariants = {
  hidden: { opacity: 0, y: 14, filter: "blur(8px)" },
  show: { opacity: 1, y: 0, filter: "blur(0px)", transition: { duration: 0.62, ease: ease.out }, transitionEnd: { filter: "none" } },
};

function Field({ label, error, help, children }) {
  return (
    <motion.label variants={itemVariants} className={"field auth-field" + (error ? " has-error" : "")}>
      <span className="auth-label">{label}</span>
      {children}
      <FieldNote error={error} help={help} />
    </motion.label>
  );
}

const matches = (query) => {
  try { return !!window.matchMedia?.(query)?.matches; } catch { return false; }
};

function Control({ glyph, children }) {
  return <span className="auth-control"><Glyph name={glyph} />{children}</span>;
}

/* Subtle parallax for the hero (fine pointers only; still under reduced motion). */
function useHeroParallax(ref) {
  useEffect(() => {
    const el = ref.current;
    if (!el || !matches("(hover: hover) and (pointer: fine)") || matches("(prefers-reduced-motion: reduce)")) return undefined;
    let raf = 0;
    let x = 0;
    let y = 0;
    const onMove = (e) => {
      x = e.clientX / window.innerWidth - 0.5;
      y = e.clientY / window.innerHeight - 0.5;
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        el.style.setProperty("--hx", x.toFixed(3));
        el.style.setProperty("--hy", y.toFixed(3));
      });
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => { window.removeEventListener("pointermove", onMove); cancelAnimationFrame(raf); };
  }, [ref]);
}

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
  // How the info notice reads: an instruction, a warning, or a success.
  const [infoTone, setInfoTone] = useState(mode === "verify-failed" ? "warn" : "info");
  const announce = (text) => { setInfoTone("ok"); setInfo(text); };
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState({});
  const [oauthPending, setOauthPending] = useState("");

  const cardRef = useRef(null);
  const heroRef = useRef(null);
  const shakeX = useMotionValue(0);
  const motionPref = useReducedMotion();
  // Read the media query directly too: the hook can report late on first paint.
  const [reducedAtMount] = useState(() => matches("(prefers-reduced-motion: reduce)"));
  const reduceMotion = motionPref || reducedAtMount;
  const firstMode = useRef(mode);
  const lastPath = useRef(location.pathname);

  useTitle(mode === "register" ? "Create account" : mode === "login" ? "Sign in" : "Account");
  useHeroParallax(heroRef);
  const fontReady = useFontReady();

  useEffect(() => {
    authApi.providers().then(r => setProviders(r.providers || [])).catch(() => {});
  }, []);

  // A stale error clears when the mode changes — but not on first paint, so
  // the ?error=oauth message from a failed provider round-trip stays visible.
  useEffect(() => {
    if (lastPath.current === location.pathname) return;
    lastPath.current = location.pathname;
    setError("");
  }, [location.pathname]);

  // Returning from a provider via the back/forward cache: the pill is idle again.
  useEffect(() => {
    const onShow = (e) => { if (e.persisted) setOauthPending(""); };
    window.addEventListener("pageshow", onShow);
    return () => window.removeEventListener("pageshow", onShow);
  }, []);

  // Focus follows the morph: the new form's first field on fine pointers
  // (no surprise keyboard on phones), otherwise its heading. On first paint,
  // settle into the first field once the card has landed — only if nothing
  // else has focus yet.
  useEffect(() => {
    const fine = matches("(hover: hover) and (pointer: fine)");
    const focusMode = () => {
      const form = cardRef.current?.querySelector(`[data-auth-mode="${mode}"]`);
      if (!form) return;
      const target = (fine && form.querySelector("input")) || form.querySelector(".auth-title");
      target?.focus({ preventScroll: true });
    };
    if (firstMode.current === mode) {
      firstMode.current = null;
      if (!fine) return undefined;
      const t = setTimeout(() => {
        if (document.activeElement === document.body || document.activeElement == null) focusMode();
      }, 1300);
      return () => clearTimeout(t);
    }
    const raf = requestAnimationFrame(focusMode);
    return () => cancelAnimationFrame(raf);
  }, [mode]);

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

  const shake = () => {
    if (reduceMotion) return;
    animate(shakeX, [0, -10, 9, -6, 4, -2, 0], { duration: 0.5, ease: "easeInOut" });
  };

  async function submit(e) {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      if (mode === "login") {
        const user = await authApi.login(identifier.trim(), password);
        onAuthed(user);
      } else if (mode === "register") {
        const user = await authApi.register(email.trim(), username.trim(), password);
        onAuthed(user);
      } else if (mode === "forgot") {
        await authApi.requestReset(email.trim());
        announce("If that email has an account, a reset link is on its way.");
        navigate("/login");
      } else if (mode === "reset") {
        await authApi.reset(token, password);
        announce("Password updated — please sign in.");
        navigate("/login");
      } else if (mode === "verify") {
        await authApi.verify(token);
        try {
          const user = await authApi.me();
          onAuthed(user);
        } catch (e2) {
          announce("Email verified — you can sign in.");
          navigate("/login");
        }
      }
    } catch (err) {
      setError(err.message || "Something went wrong.");
      shake();
    } finally {
      setBusy(false);
    }
  }

  const startOAuth = (provider) => {
    setOauthPending(provider);
    authApi.oauthStart(provider);
  };

  const title = TITLES[mode] || TITLES.login;
  const submitLabel = SUBMIT_LABELS[mode];
  const lede = LEDES[mode];
  const touch = (key) => () => setTouched(t => ({ ...t, [key]: true }));

  return (
    <div className="auth-stage" data-mode={mode} data-ready={fontReady ? "" : undefined}>
      <header className="auth-sea">
        <OceanScene className="auth-ocean" />
        <div className="auth-veil" aria-hidden="true" />
        <div className="auth-hero" ref={heroRef}>
          <Wordmark ready={fontReady} />
          <p className="auth-promise">Your novels — translated, narrated, and kept spoiler&#8209;safe.</p>
        </div>
      </header>

      <main className="auth-main">
        <motion.div ref={cardRef} className="auth-card" data-spotlight=""
                    style={{ x: shakeX }}
                    initial={reduceMotion ? false : { opacity: 0, y: 46, scale: 0.965, filter: "blur(14px)" }}
                    animate={{ opacity: 1, y: 0, scale: 1, filter: "blur(0px)", transitionEnd: { filter: "none" } }}
                    transition={{
                      default: { ...springs.gentle, delay: 0.62 },
                      opacity: { duration: 0.7, delay: 0.62, ease: ease.out },
                      filter: { duration: 0.8, delay: 0.62, ease: ease.out },
                    }}>
          <span className="auth-card-rim" aria-hidden="true" />
          <MorphHeight className="auth-morph">
            <AnimatePresence mode="popLayout">
              <PresenceForm key={mode} data-auth-mode={mode} className="auth-form" onSubmit={submit}
                           custom={firstMode.current === mode ? 0.9 : 0.1}
                           variants={formVariants} animate="show" exit="exit"
                           initial={reduceMotion && firstMode.current === mode ? false : "hidden"}>
                <motion.div variants={itemVariants} className="auth-head">
                  <h2 className="auth-title" tabIndex={-1}>{title}</h2>
                  {lede && <p className="auth-lede">{lede}</p>}
                  <AnimatePresence initial={false}>
                    {info && <AuthNotice key="info" tone={infoTone}>{info}</AuthNotice>}
                    {error && <AuthNotice key="error" tone="error">{error}</AuthNotice>}
                  </AnimatePresence>
                </motion.div>

                {mode === "register" && (
                  <>
                    <Field label="Email" error={fieldErrors.email}>
                      <Control glyph="mail">
                        <input type="email" value={email} placeholder="you@example.com" autoComplete="email"
                               onChange={e => setEmail(e.target.value)} onBlur={touch("email")} />
                      </Control>
                    </Field>
                    <Field label="Username" error={fieldErrors.username}>
                      <Control glyph="at">
                        <input value={username} placeholder="a–z, 0–9, underscore" autoComplete="username"
                               onChange={e => setUsername(e.target.value)} onBlur={touch("username")} />
                      </Control>
                    </Field>
                    <Field label="Password" error={fieldErrors.password}
                           help={!fieldErrors.password && password.length >= 8 ? "Looks good." : ""}>
                      <PasswordInput value={password} onChange={(v) => { setPassword(v); setTouched(t => ({ ...t, password: true })); }}
                                     placeholder="at least 8 characters" autoComplete="new-password" />
                    </Field>
                  </>
                )}

                {mode === "login" && (
                  <>
                    <Field label="Email or username">
                      <Control glyph="user">
                        <input value={identifier} autoComplete="username" onChange={e => setIdentifier(e.target.value)} />
                      </Control>
                    </Field>
                    <Field label="Password">
                      <PasswordInput value={password} onChange={setPassword} autoComplete="current-password" />
                    </Field>
                    <motion.div variants={itemVariants} className="auth-forgot">
                      <button type="button" className="auth-link is-quiet" onClick={() => go("/forgot")}>Forgot password?</button>
                    </motion.div>
                  </>
                )}

                {mode === "forgot" && (
                  <Field label="Email">
                    <Control glyph="mail">
                      <input type="email" value={email} placeholder="you@example.com" autoComplete="email"
                             onChange={e => setEmail(e.target.value)} />
                    </Control>
                  </Field>
                )}

                {mode === "reset" && (
                  <Field label="New password" error={fieldErrors.password}>
                    <PasswordInput value={password} onChange={(v) => { setPassword(v); setTouched(t => ({ ...t, password: true })); }}
                                   placeholder="at least 8 characters" autoComplete="new-password" />
                  </Field>
                )}

                {mode !== "verify-failed" && (
                  <motion.div variants={itemVariants} className="auth-submit">
                    <Button type="submit" variant="primary" full size="lg" loading={busy}
                            iconRight={busy ? undefined : "arrowRight"}
                            disabled={busy || (mode === "verify" && !token)}>
                      {submitLabel}
                    </Button>
                  </motion.div>
                )}

                {(mode === "login" || mode === "register") && providers.length > 0 && (
                  <motion.div variants={itemVariants} className="auth-oauth">
                    <div className="auth-divider"><span>or continue with</span></div>
                    <div className="auth-providers" data-count={Math.min(providers.length, 3)}>
                      {providers.map(p => (
                        <ProviderButton key={p} provider={p} pending={oauthPending === p}
                                        disabled={!!oauthPending} onClick={() => startOAuth(p)} />
                      ))}
                    </div>
                  </motion.div>
                )}

                <motion.div variants={itemVariants} className="auth-links">
                  {mode === "login" && (
                    <p className="auth-switch">New to Tideglass?{" "}
                      <button type="button" className="auth-link" onClick={() => go("/register")}>Create an account</button>
                    </p>
                  )}
                  {mode === "register" && (
                    <p className="auth-switch">Already have an account?{" "}
                      <button type="button" className="auth-link" onClick={() => go("/login")}>Sign in</button>
                    </p>
                  )}
                  {mode !== "login" && mode !== "register" && (
                    <button type="button" className="auth-link is-back" onClick={() => go("/login")}>
                      <Icon name="arrowLeft" size={15} /> Back to sign in
                    </button>
                  )}
                </motion.div>
              </PresenceForm>
            </AnimatePresence>
          </MorphHeight>
        </motion.div>
      </main>

      <div className="auth-top">
        <AuthBrandMark size={32} />
        <ThemeSwitch />
      </div>
    </div>
  );
}
