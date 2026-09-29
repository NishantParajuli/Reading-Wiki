/* ============================================================
   Atmosphere — which book (if any) is colouring the room right now.

   Screens declare the book in focus with `useBookAtmosphere(novel)`; the
   store resolves its palette and writes --atmo-h1/--atmo-h2/--atmo-c on
   <html> (registered @properties, so hues glide between books). The ambient
   canvas and aura subscribe to the same state. When no screen claims the
   room, it returns to the theme's accent-derived default.
   ============================================================ */
import { useEffect, useSyncExternalStore } from "react";
import { getPalette } from "./palette.js";

let state = { id: null, cover: null, title: null, palette: null };
const listeners = new Set();
let releaseTimer = null;
let token = 0;

function emit() { listeners.forEach((fn) => fn()); }

function applyCss(palette) {
  const root = document.documentElement;
  if (!palette) {
    root.style.removeProperty("--atmo-h1");
    root.style.removeProperty("--atmo-h2");
    root.style.removeProperty("--atmo-c");
    root.removeAttribute("data-atmosphere");
    return;
  }
  root.style.setProperty("--atmo-h1", String(palette.h1));
  root.style.setProperty("--atmo-h2", String(palette.h2));
  root.style.setProperty("--atmo-c", String(Math.round(palette.chroma * 1000) / 1000));
  root.setAttribute("data-atmosphere", "book");
}

export function subscribeAtmosphere(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function getAtmosphere() { return state; }

export function useAtmosphere() {
  return useSyncExternalStore(subscribeAtmosphere, getAtmosphere, getAtmosphere);
}

function claim(novel) {
  clearTimeout(releaseTimer);
  if (!novel) return;
  const id = novel.id ?? novel.title;
  if (state.id === id && state.cover === (novel.cover_url || null)) return;
  const mine = ++token;
  state = { id, cover: novel.cover_url || null, title: novel.title || "", palette: state.id === id ? state.palette : null };
  emit();
  getPalette(novel.cover_url, novel.title).then((palette) => {
    if (mine !== token) return;
    state = { ...state, palette };
    applyCss(palette);
    emit();
  });
}

function release() {
  clearTimeout(releaseTimer);
  // Defer, so moving between two screens of the same book never flickers.
  releaseTimer = setTimeout(() => {
    token += 1;
    state = { id: null, cover: null, title: null, palette: null };
    applyCss(null);
    emit();
  }, 160);
}

/** Tint the room with `novel`'s cover while the calling screen is mounted. */
export function useBookAtmosphere(novel) {
  const id = novel ? (novel.id ?? novel.title) : null;
  const cover = novel ? novel.cover_url || null : null;
  const title = novel ? novel.title || "" : "";
  useEffect(() => {
    if (id == null) return undefined;
    claim({ id, cover_url: cover, title });
    return release;
  }, [id, cover, title]);
}
