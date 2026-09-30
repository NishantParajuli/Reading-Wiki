import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Account } from "./Account.jsx";
import { SECTIONS } from "./AccountNav.jsx";
import { authApi, identityApi } from "./api.js";
import { acquisitionApi } from "../acquisition/api.js";
import { narrationApi } from "../narration/api.js";

const state = vi.hoisted(() => ({ auth: null, theme: null }));
vi.mock("../../App.jsx", () => ({ useAuth: () => state.auth, useTheme: () => state.theme }));

class InstantObserver {
  constructor(cb) { this.cb = cb; }
  observe(target) { this.cb([{ isIntersecting: true, intersectionRatio: 1, target }], this); }
  unobserve() {}
  disconnect() {}
}

/* A gauge far below the fold: never reported as on screen. */
class NeverObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function setReducedMotion(on) {
  window.matchMedia.mockImplementation((query) => ({
    matches: on && query.includes("prefers-reduced-motion") && !query.includes("no-preference"), media: query, onchange: null,
    addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
  }));
}

function Where() {
  const { pathname } = useLocation();
  return <output data-testid="where">{pathname}</output>;
}

function renderAt(path) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/account" element={<Account />} />
          <Route path="/account/:section" element={<Account />} />
          <Route path="*" element={null} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  globalThis.IntersectionObserver = InstantObserver;
  setReducedMotion(true);
  localStorage.clear();
  state.auth = {
    user: { id: 1, username: "reader", display_name: "Reader", email: "reader@example.test", email_verified: true, bio: "", prefs: {} },
    onUserUpdate: vi.fn(),
  };
  state.theme = { theme: "dark", setTheme: vi.fn(), accentHue: 192, setAccentHue: vi.fn() };
  vi.spyOn(authApi, "links").mockResolvedValue({ linked: ["google"], has_password: true });
  vi.spyOn(identityApi, "updateMe").mockImplementation(async (body) => ({ ...state.auth.user, ...body }));
  vi.spyOn(identityApi, "usage").mockResolvedValue({
    unlimited: false,
    usage: { translated_chapters: 212, ocr_pages: 40, codex_builds: 6, tts_chapters: 90 },
    limits: { translated_chapters: 1000, ocr_pages: 500, codex_builds: 20, tts_chapters: 300 },
  });
  vi.spyOn(acquisitionApi, "novelpiaCookies").mockResolvedValue({ configured: false, usable: false, cookies: [], updated_at: null });
  vi.spyOn(narrationApi, "ttsVoices").mockResolvedValue({ voices: [{ id: "dan", name: "Dan", ready: true, language: "en" }], default: "dan" });
});

afterEach(() => { document.documentElement.removeAttribute("data-theme"); });

describe("Account settings", () => {
  it("routes every section from a grouped nav and marks the current one", () => {
    renderAt("/account/reading");
    const nav = screen.getByRole("navigation", { name: "Settings sections" });
    for (const item of SECTIONS) {
      const link = within(nav).getByRole("link", { name: item.label });
      expect(link).toHaveAttribute("href", item.id === "profile" ? "/account" : `/account/${item.id}`);
    }
    expect(within(nav).getByRole("link", { name: "Reading" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("heading", { level: 1, name: "Account" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Reading" })).toBeInTheDocument();
  });

  it("keeps the section ids and falls back to profile for unknown sections", () => {
    expect(SECTIONS.map(s => s.id)).toEqual(["profile", "appearance", "reading", "audio", "security", "linked", "sources", "usage"]);
    renderAt("/account/nowhere");
    expect(screen.getByRole("heading", { level: 2, name: "Profile" })).toBeInTheDocument();
  });

  it("opens the public profile", () => {
    renderAt("/account");
    fireEvent.click(screen.getByRole("button", { name: /View public profile/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/u/reader");
  });

  it("saves the profile with trimmed fields", async () => {
    renderAt("/account");
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "  Mira  " } });
    fireEvent.change(screen.getByLabelText("Bio"), { target: { value: "Night reader." } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save profile" })));
    expect(identityApi.updateMe).toHaveBeenCalledWith({ display_name: "Mira", bio: "Night reader." });
    expect(state.auth.onUserUpdate).toHaveBeenCalled();
  });

  it("renders the Novelpia panel in Source accounts", async () => {
    renderAt("/account/sources");
    expect(await screen.findByRole("region", { name: "Novelpia Global" })).toBeInTheDocument();
  });

  it("switches theme from the preview cards", () => {
    renderAt("/account/appearance");
    const group = screen.getByRole("radiogroup", { name: "Theme" });
    expect(within(group).getByRole("radio", { name: /Tide/ })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(within(group).getByRole("radio", { name: /Pearl/ }));
    expect(state.theme.setTheme).toHaveBeenCalledWith("light");
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
  });

  it("applies an accent pebble and syncs it to the account", async () => {
    renderAt("/account/appearance");
    const pebbles = screen.getByRole("radiogroup", { name: "Accent colour" });
    expect(within(pebbles).getAllByRole("radio")).toHaveLength(7);
    expect(within(pebbles).getByRole("radio", { name: "Accent: Sea glass" })).toHaveAttribute("aria-checked", "true");
    await act(async () => fireEvent.click(within(pebbles).getByRole("radio", { name: "Accent: Coral" })));
    expect(state.theme.setAccentHue).toHaveBeenCalledWith(22);
    expect(identityApi.updateMe).toHaveBeenCalledWith({ prefs: { appearance: { accent_h: 22 } } });
    expect(await screen.findByText("Saved to your account")).toBeInTheDocument();
  });

  it("moves accent selection with the arrow keys", async () => {
    renderAt("/account/appearance");
    const first = screen.getByRole("radio", { name: "Accent: Sea glass" });
    expect(first).toHaveAttribute("tabindex", "0");
    await act(async () => fireEvent.keyDown(first, { key: "ArrowRight" }));
    expect(state.theme.setAccentHue).toHaveBeenCalledWith(165);
  });

  it("stores the ambient motion choice", () => {
    renderAt("/account/appearance");
    const group = screen.getByRole("radiogroup", { name: "Ambient motion" });
    fireEvent.click(within(group).getByRole("radio", { name: /Still/ }));
    expect(localStorage.getItem("nw-ambient")).toBe("still");
    expect(within(group).getByRole("radio", { name: /Still/ })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("Reduced motion is on")).toBeInTheDocument();
  });

  it("saves reading defaults to the account and this device", async () => {
    renderAt("/account/reading");
    fireEvent.click(screen.getByRole("radio", { name: /Sans/ }));
    fireEvent.change(screen.getByLabelText("Text size"), { target: { value: "22" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save defaults" })));
    expect(identityApi.updateMe).toHaveBeenCalledWith({ prefs: { reader: { font: "sans", size: 22, line: 1.7, width: "normal" } } });
    expect(JSON.parse(localStorage.getItem("nw-reader"))).toMatchObject({ font: "sans", size: 22 });
  });

  it("saves audio preferences", async () => {
    renderAt("/account/audio");
    expect(await screen.findByText("Preferred narrator")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "1.5×" }));
    fireEvent.click(screen.getByRole("switch", { name: /Auto-advance/ }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save audio preferences" })));
    expect(identityApi.updateMe).toHaveBeenCalledWith({ prefs: { tts: { voice: null, speed: 1.5, autoplay: false } } });
  });

  it("offers a way back when narrators are offline", async () => {
    narrationApi.ttsVoices.mockResolvedValue({ voices: [], default: null });
    renderAt("/account/audio");
    expect(await screen.findByText(/Narration voices are offline right now/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check again" })).toBeEnabled();
  });

  it("requires eight characters before setting a password", async () => {
    authApi.links.mockResolvedValue({ linked: ["google"], has_password: false });
    vi.spyOn(authApi, "changePassword").mockResolvedValue({});
    renderAt("/account/security");
    const submit = await screen.findByRole("button", { name: "Set password" });
    expect(submit).toBeDisabled();
    expect(screen.queryByLabelText("Current password")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "long enough" } });
    expect(submit).toBeEnabled();
    await act(async () => fireEvent.click(submit));
    expect(authApi.changePassword).toHaveBeenCalledWith(null, "long enough");
  });

  it("shows usage as gauges, and an honest error with a retry", async () => {
    identityApi.usage.mockRejectedValueOnce(new Error("offline"));
    renderAt("/account/usage");
    expect(await screen.findByText("Couldn't load your usage")).toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Try again" })));
    await waitFor(() => expect(screen.getByRole("progressbar", { name: /Chapters translated: 212 of 1000/ })).toBeInTheDocument());
    expect(screen.getByText("788 left")).toBeInTheDocument();
  });

  it("gives every gauge its real value, even before it scrolls into view", async () => {
    setReducedMotion(false);
    globalThis.IntersectionObserver = NeverObserver;
    renderAt("/account/usage");
    const ring = await screen.findByRole("progressbar", { name: /Chapters translated: 212 of 1000/ });
    expect(ring).toHaveAttribute("aria-valuenow", "21");
    expect(screen.getByRole("progressbar", { name: /OCR pages: 40 of 500/ })).toHaveAttribute("aria-valuenow", "8");
    // With motion allowed only the stroke waits (empty) for the gauge to arrive on screen.
    expect(ring.closest(".acct-gauge")).toHaveClass("is-waiting");
  });

  it("shows gauges filled at once under reduced motion", async () => {
    globalThis.IntersectionObserver = NeverObserver;
    renderAt("/account/usage");
    const ring = await screen.findByRole("progressbar", { name: /Chapters translated: 212 of 1000/ });
    expect(ring).toHaveAttribute("aria-valuenow", "21");
    expect(ring.closest(".acct-gauge")).not.toHaveClass("is-waiting");
  });
});
