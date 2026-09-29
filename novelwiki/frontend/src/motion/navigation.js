/* ============================================================
   Cinematic navigation.

   Every route change in the app runs through one history object. Pushes,
   replaces and back/forward POPs that change the pathname are wrapped in a
   View Transition, so the whole SPA crossfades/morphs between routes without
   any screen having to opt in. The router is a plain react-router
   `unstable_HistoryRouter`; this module only decides *how* a change animates.

   · Transition types are exposed as <html data-vt="…"> for CSS
     (see styles/transitions.css): page · pop · tab · novel-tab ·
     enter-reader · exit-reader · chapter-next · chapter-prev · theme.
   · Readiness: a destination can hold the old frame (≤ a short timeout) until
     its data is on screen, so a morph lands on real content, not a spinner.
     Screens call `useReadySignal(key, ready)`; keys come from `readinessKey`.
   · Shared covers: clicking a book link names its cover `hero-cover` for the
     duration of the transition; the novel hero's cover carries the same name,
     so the jacket flies from the grid into the hero.
   Reduced motion or no View Transitions support → plain instant navigation.
   ============================================================ */
import { useEffect } from "react";
import { flushSync } from "react-dom";
import { createBrowserHistory } from "@remix-run/router";

const doc = typeof document !== "undefined" ? document : null;

export function supportsViewTransitions() {
  return !!(doc && typeof doc.startViewTransition === "function");
}

export function prefersReducedMotion() {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; }
  catch { return false; }
}

function canAnimate() {
  return supportsViewTransitions() && !prefersReducedMotion() && doc.visibilityState === "visible";
}

/* ---------------- readiness ---------------- */
const readyKeys = new Set();
const waiters = new Map();

export function markReady(key) {
  if (!key) return;
  readyKeys.add(key);
  const pending = waiters.get(key);
  if (pending) { waiters.delete(key); pending.forEach(resolve => resolve()); }
}

export function unmarkReady(key) { if (key) readyKeys.delete(key); }

export function waitReady(key, timeout = 600) {
  if (!key || readyKeys.has(key)) return Promise.resolve();
  return new Promise(resolve => {
    const set = waiters.get(key) || new Set();
    const done = () => { set.delete(resolve); resolve(); };
    set.add(resolve);
    waiters.set(key, set);
    setTimeout(done, timeout);
  });
}

/* Route chunks still arriving: RouteBoundary's loading orb holds the old frame
   while it is on screen, so a first visit morphs into the page, not the orb. */
let pendingScreens = 0;
const screenWaiters = new Set();

export function holdForScreen() {
  pendingScreens += 1;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    pendingScreens -= 1;
    if (!pendingScreens) { screenWaiters.forEach(resolve => resolve()); screenWaiters.clear(); }
  };
}

function waitScreens(timeout) {
  if (!pendingScreens) return Promise.resolve();
  return new Promise(resolve => {
    screenWaiters.add(resolve);
    setTimeout(() => { screenWaiters.delete(resolve); resolve(); }, timeout);
  });
}

/* Everything a destination needs before the new frame is captured. */
function waitDestination(key, timeout) {
  return Promise.all([key ? waitReady(key, timeout) : null, waitScreens(timeout)]);
}

/** Mark `key` ready while `ready` is true and the caller is mounted. */
export function useReadySignal(key, ready) {
  useEffect(() => {
    if (!key || !ready) return undefined;
    markReady(key);
    return () => unmarkReady(key);
  }, [key, ready]);
}

const READER_RE = /^\/n\/(\d+)\/read\/([^/]+)\/?$/;
const NOVEL_RE = /^\/n\/(\d+)(?:\/|$)/;

export function readinessKey(pathname) {
  const reader = pathname.match(READER_RE);
  if (reader) return `chapter:${reader[1]}:${Number(reader[2])}`;
  const novel = pathname.match(NOVEL_RE);
  if (novel) return `novel:${novel[1]}`;
  if (pathname === "/") return "home";
  if (pathname === "/library") return "library";
  return null;
}

/* ---------------- transition types ---------------- */
function section(pathname) {
  if (pathname.startsWith("/account")) return "account";
  if (pathname.startsWith("/admin")) return "admin";
  return null;
}

export function classifyTransition(from, to, isPop = false) {
  const a = from.match(READER_RE);
  const b = to.match(READER_RE);
  if (a && b && a[1] === b[1]) return Number(b[2]) >= Number(a[2]) ? "chapter-next" : "chapter-prev";
  if (b && !a) return "enter-reader";
  if (a && !b) return "exit-reader";
  const na = from.match(NOVEL_RE);
  const nb = to.match(NOVEL_RE);
  if (na && nb && na[1] === nb[1]) return "novel-tab";
  if (section(from) && section(from) === section(to)) return "tab";
  return isPop ? "pop" : "page";
}

const HOLD = { "chapter-next": 900, "chapter-prev": 900, "enter-reader": 900, page: 520, pop: 420, tab: 260, "novel-tab": 320, "exit-reader": 520 };

/* Elements named for the duration of a single transition (shared covers). */
const temporaryNames = new Set();
function clearTemporaryNames() {
  temporaryNames.forEach(el => { el.style.viewTransitionName = ""; });
  temporaryNames.clear();
}

let transitionCount = 0;

/**
 * Run `update` inside a view transition tagged `type`. `update` may return a
 * promise (the old frame holds until it settles). Falls back to a plain call.
 */
export function runViewTransition(type, update) {
  if (!canAnimate()) {
    clearTemporaryNames();
    const result = update();
    return result && typeof result.then === "function" ? result : Promise.resolve();
  }
  const root = doc.documentElement;
  const id = ++transitionCount;
  root.dataset.vt = type;
  let transition;
  try {
    transition = doc.startViewTransition(update);
  } catch {
    delete root.dataset.vt;
    clearTemporaryNames();
    update();
    return Promise.resolve();
  }
  // A skipped/aborted transition rejects `ready`; that's expected, not an error.
  transition.ready.catch(() => {});
  transition.updateCallbackDone.catch(() => {});
  transition.finished.catch(() => {}).finally(() => {
    if (id === transitionCount) {
      delete root.dataset.vt;
      clearTemporaryNames();
    }
  });
  return transition.finished.catch(() => {});
}

function pathnameOf(to) {
  if (typeof to === "string") {
    try { return new URL(to, window.location.href).pathname; } catch { return to; }
  }
  return to && to.pathname ? to.pathname : window.location.pathname;
}

/* ---------------- history ---------------- */
export function createTransitionHistory() {
  const history = createBrowserHistory({ v5Compat: true });
  const rawPush = history.push;
  const rawReplace = history.replace;
  const rawListen = history.listen;
  // v5Compat notifies the listener for pushes/replaces too, so lastPath always
  // mirrors the rendered location.
  let lastPath = window.location.pathname;
  const bootedAt = Date.now();

  const animated = (commit, to) => {
    const from = window.location.pathname;
    const next = pathnameOf(to);
    // Query-only changes (filters, search) and the first paint never animate.
    if (next === from || Date.now() - bootedAt < 400 || !canAnimate()) { commit(); return; }
    const type = classifyTransition(from, next);
    const key = readinessKey(next);
    runViewTransition(type, () => {
      flushSync(commit);
      return waitDestination(key, HOLD[type] || 500);
    });
  };

  history.push = (to, state) => animated(() => rawPush(to, state), to);
  history.replace = (to, state) => animated(() => rawReplace(to, state), to);
  history.listen = (fn) => rawListen((update) => {
    const next = update.location.pathname;
    const from = lastPath;
    lastPath = next;
    if (update.action !== "POP" || next === from || !canAnimate()) { fn(update); return; }
    const type = classifyTransition(from, next, true);
    const key = readinessKey(next);
    runViewTransition(type, () => {
      flushSync(() => fn(update));
      return waitDestination(key, Math.min(HOLD[type] || 400, 500));
    });
  });
  return history;
}

/* ---------------- shared cover morph ---------------- */
const NOVEL_LINK_RE = /^\/n\/\d+\/?(?:$|chapters|codex|ask|manage)/;

/**
 * Capture-phase click listener: when a book link is followed, name the cover
 * it belongs to so it morphs into the novel hero. Install once at boot.
 */
export function installCoverMorph() {
  if (!doc) return () => {};
  const onClick = (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest && event.target.closest("a[href]");
    if (!link || link.target === "_blank") return;
    let url;
    try { url = new URL(link.href, window.location.href); } catch { return; }
    if (url.origin !== window.location.origin || !NOVEL_LINK_RE.test(url.pathname)) return;
    // A novel hero already on screen carries the name itself (and morphs into
    // the next hero); naming a second jacket would cancel the transition.
    if (doc.querySelector("[data-vt-hero]")) return;
    const scope = link.closest("[data-vt-card]") || link;
    const cover = scope.querySelector("[data-vt-cover]");
    if (!cover || cover.closest("[data-vt-hero]")) return;
    clearTemporaryNames();
    cover.style.viewTransitionName = "hero-cover";
    temporaryNames.add(cover);
    // If no transition consumes the name, drop it so names never collide.
    setTimeout(() => { if (temporaryNames.has(cover) && !doc.documentElement.dataset.vt) clearTemporaryNames(); }, 1200);
  };
  doc.addEventListener("click", onClick, true);
  return () => doc.removeEventListener("click", onClick, true);
}

/* ---------------- theme ripple ---------------- */
/** Switch themes with a circular reveal expanding from `origin` ({x, y}). */
export function transitionTheme(apply, origin) {
  if (!canAnimate()) { apply(); return; }
  const root = doc.documentElement;
  const x = origin && Number.isFinite(origin.x) ? origin.x : window.innerWidth - 40;
  const y = origin && Number.isFinite(origin.y) ? origin.y : 40;
  const r = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
  root.style.setProperty("--vt-x", `${x}px`);
  root.style.setProperty("--vt-y", `${y}px`);
  root.style.setProperty("--vt-r", `${Math.ceil(r)}px`);
  runViewTransition("theme", () => { flushSync(apply); });
}
