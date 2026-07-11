/* ============================================================
   Root — providers (query client, toasts, citations, auth, theme) and the
   route table. The auth gate resolves the session before anything renders;
   a mid-session 401 re-gates and returns the user to the interrupted URL
   after they sign back in.
   ============================================================ */
import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate, useLocation, useNavigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { API, setUnauthorizedHandler } from "./lib/api.js";
import { CiteProvider } from "./lib/markdown.jsx";
import { ToastProvider, useToast } from "./components/toast.jsx";
import { Shell } from "./layouts/Shell.jsx";
import { NovelLayout } from "./layouts/NovelLayout.jsx";
import { AuthScreen } from "./screens/auth/AuthScreen.jsx";
import { Home } from "./screens/Home.jsx";
import { Library } from "./screens/Library.jsx";
import { Discover } from "./screens/Discover.jsx";
import { Jobs } from "./screens/Jobs.jsx";
import { ImportView } from "./screens/ImportView.jsx";
import { Overview } from "./screens/novel/Overview.jsx";
import { Chapters } from "./screens/novel/Chapters.jsx";
import { Manage } from "./screens/novel/Manage.jsx";
import { Reader } from "./screens/Reader.jsx";
import { CodexBrowser } from "./screens/codex/Browser.jsx";
import { EntityPage } from "./screens/codex/Entity.jsx";
import { Ask } from "./screens/codex/Ask.jsx";
import { Profile } from "./screens/Profile.jsx";
import { Account } from "./screens/Account.jsx";
import { Admin } from "./screens/Admin.jsx";

/* ---------- Auth context ---------- */
const AuthContext = createContext({ user: null });
export const useAuth = () => useContext(AuthContext);

/* ---------- Theme context ---------- */
const ThemeContext = createContext({ theme: "light" });
export const useTheme = () => useContext(ThemeContext);

function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(() => {
    const t = localStorage.getItem("nw-theme");
    if (t === "light" || t === "dark") return t;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  const [accentHue, setAccentHue] = useState(() => {
    const h = parseInt(localStorage.getItem("nw-accent-h") || "", 10);
    return isNaN(h) ? 64 : h;
  });
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("nw-theme", theme);
  }, [theme]);
  useEffect(() => {
    document.documentElement.style.setProperty("--accent-h", accentHue);
    localStorage.setItem("nw-accent-h", String(accentHue));
  }, [accentHue]);
  const value = useMemo(() => ({ theme, setTheme, accentHue, setAccentHue }), [theme, accentHue]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
});

/* Old hash URLs (#/u/x, #/account, #/admin, #/reset?token=…) → real paths. */
function HashRedirectShim() {
  const navigate = useNavigate();
  useEffect(() => {
    const raw = (window.location.hash || "").replace(/^#\/?/, "");
    if (!raw) return;
    const [path, query] = raw.split("?");
    const q = query ? `?${query}` : "";
    const map = {
      account: "/account", admin: "/admin", login: "/login", register: "/register",
      reset: "/reset", verify: "/verify", "verify-failed": "/verify-failed", verified: "/login",
    };
    let dest = null;
    if (path.startsWith("u/")) dest = `/u/${path.slice(2)}`;
    else if (map[path]) dest = map[path];
    if (dest) {
      history.replaceState(null, "", window.location.pathname);
      navigate(dest + q, { replace: true });
    }
  }, [navigate]);
  return null;
}

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo({ top: 0 }); }, [pathname]);
  return null;
}

/* The signed-in app: shell routes + full-bleed reader route. */
function AppRoutes() {
  return (
    <Routes>
      <Route path="/n/:novelId/read/:number" element={<Reader />} />
      <Route element={<Shell />}>
        <Route path="/" element={<Home />} />
        <Route path="/library" element={<Library />} />
        <Route path="/discover" element={<Discover />} />
        <Route path="/import" element={<ImportView />} />
        <Route path="/jobs" element={<Jobs />} />
        <Route path="/u/:username" element={<Profile />} />
        <Route path="/account" element={<Account />} />
        <Route path="/account/:section" element={<Account />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="/admin/:tab" element={<Admin />} />
        <Route path="/n/:novelId" element={<NovelLayout />}>
          <Route index element={<Overview />} />
          <Route path="chapters" element={<Chapters />} />
          <Route path="manage" element={<Manage />} />
          <Route path="codex" element={<CodexBrowser />} />
          <Route path="codex/e/:entityId" element={<EntityPage />} />
          <Route path="ask" element={<Ask />} />
        </Route>
      </Route>
      {/* signed-in user hitting an auth path → home */}
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route path="/register" element={<Navigate to="/" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function AuthedApp({ user, setUser, onLogout }) {
  const value = useMemo(() => ({
    user,
    onUserUpdate: setUser,
    logout: onLogout,
  }), [user, setUser, onLogout]);
  return (
    <AuthContext.Provider value={value}>
      <AppRoutes />
    </AuthContext.Provider>
  );
}

function Gate() {
  const [state, setState] = useState({ loading: true, user: null });
  const location = useLocation();
  const navigate = useNavigate();
  const { toast } = useToast();

  useEffect(() => {
    let cancel = false;
    API.auth.me()
      .then(u => { if (!cancel) setState({ loading: false, user: u }); })
      .catch(() => { if (!cancel) setState({ loading: false, user: null }); });
    return () => { cancel = true; };
  }, []);

  // Mid-session 401 → drop the user, remember where they were, toast.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setState(s => {
        if (!s.user) return s;
        sessionStorage.setItem("nw-return-to", window.location.pathname + window.location.search);
        toast("Session expired — please sign in again.", { tone: "info" });
        return { loading: false, user: null };
      });
    });
    return () => setUnauthorizedHandler(null);
  }, [toast]);

  if (state.loading) {
    return (
      <div style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
        <div className="spinner lg" aria-label="Loading" />
      </div>
    );
  }

  const authPaths = ["/login", "/register", "/forgot", "/reset", "/verify", "/verify-failed"];
  const onAuthPath = authPaths.some(p => location.pathname === p || location.pathname.startsWith(p + "/"));
  const forceVerify = location.pathname === "/verify"; // allow verifying while signed in

  if (!state.user || forceVerify) {
    if (state.user && !forceVerify) return null;
    if (!onAuthPath) {
      sessionStorage.setItem("nw-return-to", location.pathname + location.search);
      return <Navigate to="/login" replace />;
    }
    return (
      <AuthScreen
        onAuthed={(u) => {
          setState({ loading: false, user: u });
          queryClient.clear();
          const dest = sessionStorage.getItem("nw-return-to") || "/";
          sessionStorage.removeItem("nw-return-to");
          navigate(dest === "/login" ? "/" : dest, { replace: true });
        }}
      />
    );
  }

  return (
    <AuthedApp
      user={state.user}
      setUser={(u) => setState(s => ({ ...s, user: u }))}
      onLogout={async () => {
        try { await API.auth.logout(); } catch (e) { /* session may already be gone */ }
        queryClient.clear();
        setState({ loading: false, user: null });
        navigate("/login");
      }}
    />
  );
}

export function Root() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ToastProvider>
          <CiteProvider>
            <BrowserRouter>
              <HashRedirectShim />
              <ScrollToTop />
              <Gate />
            </BrowserRouter>
          </CiteProvider>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
