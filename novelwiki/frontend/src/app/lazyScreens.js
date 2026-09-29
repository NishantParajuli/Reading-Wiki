/* Route screens load on demand, so the first paint ships only the shell and
   the screen you asked for; the rest are fetched while the browser is idle.
   Each screen is its own chunk, so a failed chunk load (e.g. a stale tab after
   a deploy) is contained to that route and recoverable (see RouteBoundary). */
import { lazy } from "react";

const loaders = {
  Home: () => import("../modules/experience/Home.jsx"),
  Library: () => import("../modules/catalog/Library.jsx"),
  Discover: () => import("../modules/catalog/Discover.jsx"),
  Overview: () => import("../modules/catalog/Overview.jsx"),
  Manage: () => import("../modules/catalog/Manage.jsx"),
  Jobs: () => import("../modules/work/Jobs.jsx"),
  ImportView: () => import("../modules/acquisition/ImportView.jsx"),
  Chapters: () => import("../modules/reading/Chapters.jsx"),
  Reader: () => import("../modules/reading/Reader.jsx"),
  CodexBrowser: () => import("../modules/codex/Browser.jsx"),
  EntityPage: () => import("../modules/codex/Entity.jsx"),
  Ask: () => import("../modules/codex/Ask.jsx"),
  Admin: () => import("../modules/admin/Admin.jsx"),
  Profile: () => import("../modules/identity/Profile.jsx"),
  Account: () => import("../modules/identity/Account.jsx"),
  AuthScreen: () => import("../modules/identity/AuthScreen.jsx"),
};

const screens = {};
for (const [name, load] of Object.entries(loaders)) {
  screens[name] = lazy(() => load().then((module) => ({ default: module[name] })));
}

export const {
  Home, Library, Discover, Overview, Manage, Jobs, ImportView, Chapters, Reader,
  CodexBrowser, EntityPage, Ask, Admin, Profile, Account, AuthScreen,
} = screens;

/** Warm every screen chunk once the app is idle (errors are ignored here and
    surface, recoverably, only if that screen is actually opened). */
export function preloadScreens() {
  const run = () => Object.values(loaders).forEach((load) => { load().catch(() => {}); });
  if (typeof window === "undefined") return;
  if ("requestIdleCallback" in window) window.requestIdleCallback(run, { timeout: 4000 });
  else setTimeout(run, 1500);
}
