/* ============================================================
   Root — providers (query client, toasts, citations, auth, theme) and the
   route table. The auth gate resolves the session before anything renders;
   a mid-session 401 re-gates and returns the user to the interrupted URL
   after they sign back in.
   ============================================================ */
import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import { unstable_HistoryRouter as HistoryRouter, Routes, Route, Navigate, useLocation, useNavigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionConfig } from "motion/react";

import { authApi } from "../modules/identity/api.js";
import { setUnauthorizedHandler } from "../shared/api/http.js";
import { CiteProvider } from "../lib/markdown.jsx";
import { ToastProvider, useToast } from "../components/toast.jsx";
import { Shell } from "../layouts/Shell.jsx";
import { NovelLayout } from "../layouts/NovelLayout.jsx";
import {
  AuthScreen, Profile, Account, Home, NotFound, Library, Discover, Overview, Jobs, ImportView,
  Chapters, Reader, Manage, CodexBrowser, EntityPage, Ask, Admin, preloadScreens,
} from "./lazyScreens.js";
import { RouteBoundary } from "./RouteBoundary.jsx";
import { createTransitionHistory, installCoverMorph } from "../motion/navigation.js";
import { installPointerFX } from "../motion/pointerFX.js";

/* ---------- Auth context ---------- */
const AuthContext = createContext({ user: null });
export const useAuth = () => useContext(AuthContext);

/* ---------- Theme context ---------- */
export const DEFAULT_ACCENT_H = 192;
const ThemeContext = createContext({ theme: "light" });
export const useTheme = () => useContext(ThemeContext);

function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(() => {
    const t = localStorage.getItem("nw-theme");
    if (t === "light" || t === "dark") return t;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  const [accentHue, setAccentHue] = useState(() => {
    let h = NaN;
    try {
      h = parseInt(localStorage.getItem("nw-accent-h") || "", 10);
      // 165 was the previous design's implicit default (never a chosen swatch):
      // move those readers onto the sea-glass default once.
      if (h === 165 && localStorage.getItem("nw-design") !== "tideglass-2") h = NaN;
      localStorage.setItem("nw-design", "tideglass-2");
    } catch { /* storage unavailable */ }
    return Number.isFinite(h) && h >= 0 && h <= 360 ? h : DEFAULT_ACCENT_H;
  });
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("nw-theme", theme); } catch { /* storage unavailable */ }
    const meta = document.querySelectorAll('meta[name="theme-color"]');
    meta.forEach(m => m.setAttribute("content", theme === "dark" ? "#0a0f1c" : "#f8f6f1"));
  }, [theme]);
  useEffect(() => {
    document.documentElement.style.setProperty("--accent-h", accentHue);
    try { localStorage.setItem("nw-accent-h", String(accentHue)); } catch { /* storage unavailable */ }
  }, [accentHue]);
  const value = useMemo(() => ({ theme, setTheme, accentHue, setAccentHue }), [theme, accentHue]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

/* Every navigation runs through one transition-aware history (see motion/navigation.js). */
const history = typeof window !== "undefined" ? createTransitionHistory() : null;
if (typeof window !== "undefined") {
  installPointerFX();
  installCoverMorph();
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
      <Route path="/n/:novelId/read/:number" element={<RouteBoundary><Reader /></RouteBoundary>} />
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
        <Route path="*" element={<NotFound />} />
      </Route>
      {/* signed-in user hitting an auth path → home */}
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route path="/register" element={<Navigate to="/" replace />} />
      <Route path="/forgot" element={<Navigate to="/" replace />} />
      <Route path="/reset" element={<Navigate to="/" replace />} />
      <Route path="/verify-failed" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function AuthedApp({ user, setUser, onLogout }) {
  useEffect(() => { preloadScreens(); }, []);
  // The accent chosen in Account → Appearance follows the reader across devices.
  const { setAccentHue } = useTheme();
  const savedAccent = Number(user && user.prefs && user.prefs.appearance && user.prefs.appearance.accent_h);
  useEffect(() => {
    if (Number.isFinite(savedAccent) && savedAccent >= 0 && savedAccent <= 360) setAccentHue(savedAccent);
  }, [savedAccent, setAccentHue]);
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
    authApi.me()
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
      <div className="boot-screen" role="status" aria-label="Loading">
        <span className="boot-orb" aria-hidden="true" />
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
      <RouteBoundary><AuthScreen
        onAuthed={(u) => {
          setState({ loading: false, user: u });
          queryClient.clear();
          const dest = sessionStorage.getItem("nw-return-to") || "/";
          sessionStorage.removeItem("nw-return-to");
          navigate(dest === "/login" ? "/" : dest, { replace: true });
        }}
      /></RouteBoundary>
    );
  }

  return (
    <AuthedApp
      user={state.user}
      setUser={(u) => setState(s => ({ ...s, user: u }))}
      onLogout={async () => {
        try { await authApi.logout(); } catch (e) { /* session may already be gone */ }
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
      <MotionConfig reducedMotion="user">
        <ThemeProvider>
          <ToastProvider>
            <CiteProvider>
              <HistoryRouter history={history}>
                <HashRedirectShim />
                <ScrollToTop />
                <Gate />
              </HistoryRouter>
            </CiteProvider>
          </ToastProvider>
        </ThemeProvider>
      </MotionConfig>
    </QueryClientProvider>
  );
}
