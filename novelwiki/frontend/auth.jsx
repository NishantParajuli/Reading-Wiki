/* ============================================================
   auth.jsx — login / register / password-reset gate + the appbar user menu.

   Style note: this file matches the rest of the app — plain React.createElement
   (aliased to `h` for legibility), hooks pulled from the global React destructure
   in components.jsx. Sign-in uses the cookie session set by /api/auth/*.
   ============================================================ */
const h = React.createElement;

// Read the SPA hash route (#/reset?token=… , #/verified, #/login?error=oauth).
function readHash() {
  const raw = (window.location.hash || "").replace(/^#\/?/, "");
  const [path, query] = raw.split("?");
  const params = new URLSearchParams(query || "");
  return { path: path || "", params };
}

function AuthField({ label, type, value, onChange, placeholder, autoComplete }) {
  return h("label", { className: "auth-field" },
    h("span", { className: "auth-label" }, label),
    h("input", {
      className: "auth-input", type: type || "text", value, placeholder,
      autoComplete, onChange: (e) => onChange(e.target.value),
    })
  );
}

function OAuthButtons({ providers }) {
  if (!providers || providers.length === 0) return null;
  const names = { google: "Google", discord: "Discord" };
  return h("div", { className: "auth-oauth" },
    h("div", { className: "auth-divider" }, h("span", null, "or continue with")),
    providers.map((p) => h("button", {
      key: p, type: "button", className: "auth-oauth-btn",
      onClick: () => window.API.auth.oauthStart(p),
    }, names[p] || p))
  );
}

function AuthScreen({ onAuthed }) {
  const initial = readHash();
  const [mode, setMode] = useState(initial.path === "reset" ? "reset" : initial.path === "verify" ? "verify" : "login");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [resetToken] = useState(initial.path === "reset" ? initial.params.get("token") || "" : "");
  const [verifyToken] = useState(initial.path === "verify" ? initial.params.get("token") || "" : "");
  const [providers, setProviders] = useState([]);
  const [error, setError] = useState(initial.params.get("error") === "oauth" ? "Sign-in with that provider failed." : "");
  const [info, setInfo] = useState(
    initial.path === "verify" ? "Confirm your email to finish verification." :
    initial.path === "verified" ? "Email verified — you can sign in." :
    initial.path === "verify-failed" ? "That verification link is invalid or expired." : ""
  );
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    window.API.auth.providers().then((r) => setProviders(r.providers || [])).catch(() => {});
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      if (mode === "login") {
        const user = await window.API.auth.login(identifier.trim(), password);
        onAuthed(user);
      } else if (mode === "register") {
        const user = await window.API.auth.register(email.trim(), username.trim(), password);
        onAuthed(user);
      } else if (mode === "forgot") {
        await window.API.auth.requestReset(email.trim());
        setInfo("If that email has an account, a reset link is on its way.");
        setMode("login");
      } else if (mode === "reset") {
        await window.API.auth.reset(resetToken, password);
        setInfo("Password updated — please sign in.");
        setMode("login");
        window.location.hash = "";
      } else if (mode === "verify") {
        await window.API.auth.verify(verifyToken);
        window.location.hash = "";
        try {
          const user = await window.API.auth.me();
          onAuthed(user);
        } catch (e) {
          setInfo("Email verified — you can sign in.");
          setMode("login");
        }
      }
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  const isLogin = mode === "login";
  const isRegister = mode === "register";
  const isForgot = mode === "forgot";
  const isReset = mode === "reset";
  const isVerify = mode === "verify";

  const title = isReset ? "Set a new password"
    : isForgot ? "Reset your password"
    : isVerify ? "Verify your email"
    : isRegister ? "Create your account" : "Welcome back";

  const fields = [];
  if (isRegister) {
    fields.push(h(AuthField, { key: "email", label: "Email", type: "email", value: email, onChange: setEmail, placeholder: "you@example.com", autoComplete: "email" }));
    fields.push(h(AuthField, { key: "username", label: "Username", value: username, onChange: setUsername, placeholder: "a–z, 0–9, underscore", autoComplete: "username" }));
    fields.push(h(AuthField, { key: "pw", label: "Password", type: "password", value: password, onChange: setPassword, placeholder: "at least 8 characters", autoComplete: "new-password" }));
  } else if (isLogin) {
    fields.push(h(AuthField, { key: "id", label: "Email or username", value: identifier, onChange: setIdentifier, autoComplete: "username" }));
    fields.push(h(AuthField, { key: "pw", label: "Password", type: "password", value: password, onChange: setPassword, autoComplete: "current-password" }));
  } else if (isForgot) {
    fields.push(h(AuthField, { key: "email", label: "Email", type: "email", value: email, onChange: setEmail, placeholder: "you@example.com", autoComplete: "email" }));
  } else if (isReset) {
    fields.push(h(AuthField, { key: "pw", label: "New password", type: "password", value: password, onChange: setPassword, placeholder: "at least 8 characters", autoComplete: "new-password" }));
  }

  const submitLabel = isReset ? "Update password"
    : isForgot ? "Send reset link"
    : isVerify ? "Verify email"
    : isRegister ? "Create account" : "Sign in";

  return h("div", { className: "auth-wrap" },
    h("form", { className: "auth-card", onSubmit: submit },
      h("div", { className: "auth-brand" },
        h("div", { className: "brand-mark" }, h(Icon, { name: "book", size: 22 })),
        h("div", { className: "auth-brand-name" }, "Tideglass")
      ),
      h("h1", { className: "auth-title" }, title),
      info && h("div", { className: "auth-info" }, info),
      error && h("div", { className: "auth-error" }, error),
      fields,
      h("button", { className: "auth-submit", type: "submit", disabled: busy || (isVerify && !verifyToken) },
        busy ? "…" : submitLabel),
      (isLogin || isRegister) && h(OAuthButtons, { providers }),
      h("div", { className: "auth-links" },
        isLogin && h("button", { type: "button", className: "auth-linkbtn", onClick: () => { setError(""); setMode("forgot"); } }, "Forgot password?"),
        isLogin && h("button", { type: "button", className: "auth-linkbtn", onClick: () => { setError(""); setMode("register"); } }, "Create an account"),
        !isLogin && h("button", { type: "button", className: "auth-linkbtn", onClick: () => { setError(""); setMode("login"); window.location.hash = ""; } }, "← Back to sign in")
      )
    )
  );
}

function QuotaLine({ label, used, limit }) {
  const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return h("div", { className: "usermenu-quota" },
    h("div", { className: "usermenu-quota-top" },
      h("span", null, label),
      h("span", { className: "muted" }, `${used} / ${limit}`)
    ),
    h("div", { className: "progress-track" }, h("div", { className: "progress-fill", style: { width: pct + "%" } }))
  );
}

function UserMenu({ user, onLogout, onProfile, onAccount, onAdmin }) {
  const [open, setOpen] = useState(false);
  const [usage, setUsage] = useState(null);
  const ref = useRef(null);
  useEffect(() => {
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);
  // Load quota usage the first time the menu is opened.
  useEffect(() => {
    if (open && usage == null) {
      window.API.usage().then(setUsage).catch(() => setUsage({ unlimited: true }));
    }
  }, [open, usage]);
  const name = user.display_name || user.username;
  const initial = (name || "?").trim().charAt(0).toUpperCase();
  const go = (fn) => () => { setOpen(false); fn && fn(); };
  const doLogout = async () => {
    try { await window.API.auth.logout(); } catch (e) {}
    onLogout();
  };
  const avatar = user.avatar_url
    ? h("img", { className: "usermenu-avatar usermenu-avatar-img", src: user.avatar_url, alt: "", onClick: () => setOpen((o) => !o), title: name })
    : h("button", { className: "usermenu-avatar", onClick: () => setOpen((o) => !o), "aria-label": "Account menu", title: name }, initial);
  return h("div", { className: "usermenu", ref },
    avatar,
    open && h("div", { className: "usermenu-pop" },
      h("div", { className: "usermenu-head" },
        h("div", { className: "usermenu-name" }, name),
        h("div", { className: "usermenu-email muted" }, user.email)
      ),
      !user.email_verified && h("div", { className: "usermenu-warn" }, "Email not verified — check your inbox to unlock translation & uploads."),
      usage && !usage.unlimited && h("div", { className: "usermenu-usage" },
        h("div", { className: "usermenu-usage-title muted" }, "This month"),
        h(QuotaLine, { label: "Chapters translated", used: usage.usage.translated_chapters, limit: usage.limits.translated_chapters }),
        h(QuotaLine, { label: "OCR pages", used: usage.usage.ocr_pages, limit: usage.limits.ocr_pages })
      ),
      usage && usage.unlimited && h("div", { className: "usermenu-tag" }, "Unlimited usage"),
      h("div", { className: "usermenu-sep" }),
      h("button", { className: "usermenu-item", onClick: go(() => onProfile && onProfile(user.username)) }, "Profile"),
      h("button", { className: "usermenu-item", onClick: go(onAccount) }, "Account & quota"),
      user.role === "admin" && h("button", { className: "usermenu-item", onClick: go(onAdmin) }, "Admin"),
      h("div", { className: "usermenu-sep" }),
      h("button", { className: "usermenu-item", onClick: doLogout }, "Sign out")
    )
  );
}

window.AuthScreen = AuthScreen;
window.UserMenu = UserMenu;
