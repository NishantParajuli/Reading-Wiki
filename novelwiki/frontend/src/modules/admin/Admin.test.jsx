import React from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Admin } from "./Admin.jsx";
import { ADMIN_TABS } from "./AdminPanels.jsx";
import { adminApi } from "./api.js";
import { acquisitionApi } from "../acquisition/api.js";
import { catalogApi } from "../catalog/api.js";

const state = vi.hoisted(() => ({ auth: null }));
vi.mock("../../App.jsx", () => ({ useAuth: () => state.auth, useTheme: () => ({}) }));

class InstantObserver {
  constructor(cb) { this.cb = cb; }
  observe(target) { this.cb([{ isIntersecting: true, intersectionRatio: 1, target }], this); }
  unobserve() {}
  disconnect() {}
}

const me = {
  id: 1, username: "reader", display_name: "Reader", email: "reader@example.test", role: "admin", status: "active",
  email_verified: true, quota_overrides: {}, ai_backend_policy: {},
  usage: { translated_chapters: 0, ocr_pages: 0, codex_builds: 0, tts_chapters: 0 },
  limits: { translated_chapters: 100, ocr_pages: 100, codex_builds: 100, tts_chapters: 100 },
};
const ari = {
  ...me, id: 2, username: "ari", display_name: "Ari", email: "ari@example.test", role: "user",
  usage: { translated_chapters: 90, ocr_pages: 0, codex_builds: 1, tts_chapters: 12 },
};

function Where() {
  return <output data-testid="where">{useLocation().pathname}</output>;
}

function renderAdmin(path = "/admin") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/admin" element={<Admin />} />
        <Route path="/admin/:tab" element={<Admin />} />
        <Route path="*" element={null} />
      </Routes>
      <Where />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  globalThis.IntersectionObserver = InstantObserver;
  window.matchMedia.mockImplementation((query) => ({
    matches: query.includes("prefers-reduced-motion") && !query.includes("no-preference"), media: query, onchange: null,
    addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
  }));
  state.auth = { user: me };
  vi.spyOn(adminApi, "users").mockResolvedValue([me, ari]);
  vi.spyOn(adminApi, "updateUser").mockResolvedValue({ status: "success" });
  vi.spyOn(adminApi, "deleteUser").mockResolvedValue({ status: "success" });
});

describe("Admin console", () => {
  it("guards the page for non-admins", () => {
    state.auth = { user: { ...me, role: "user" } };
    renderAdmin();
    expect(screen.getByText("Admins only")).toBeInTheDocument();
    expect(adminApi.users).not.toHaveBeenCalled();
  });

  it("lists users with self-guards on your own row", async () => {
    renderAdmin();
    expect(screen.getByRole("heading", { name: "Admin" })).toBeInTheDocument();
    const mine = await screen.findByRole("article", { name: "Reader (@reader)" });
    expect(within(mine).getByText("@reader")).toBeInTheDocument();
    expect(within(mine).getByRole("combobox", { name: "Account status for @reader" })).toBeDisabled();
    expect(within(mine).getByRole("button", { name: "Demote" })).toBeDisabled();
    expect(within(mine).getByRole("button", { name: "Delete @reader" })).toBeDisabled();
    const theirs = screen.getByRole("article", { name: "Ari (@ari)" });
    expect(within(theirs).getByRole("button", { name: "Make admin" })).toBeEnabled();
    expect(within(theirs).getByRole("progressbar", { name: "@ari — Chapters: 90 of 100" })).toHaveAttribute("aria-valuenow", "90");
  });

  it("changes status and role", async () => {
    renderAdmin();
    const theirs = await screen.findByRole("article", { name: "Ari (@ari)" });
    await act(async () => fireEvent.change(within(theirs).getByRole("combobox", { name: "Account status for @ari" }), { target: { value: "suspended" } }));
    expect(adminApi.updateUser).toHaveBeenCalledWith(2, { status: "suspended" });
    await act(async () => fireEvent.click(within(theirs).getByRole("button", { name: "Make admin" })));
    expect(adminApi.updateUser).toHaveBeenCalledWith(2, { role: "admin" });
  });

  it("unfolds the quota and AI access editor and saves limits", async () => {
    vi.spyOn(adminApi, "saveAiPolicy").mockResolvedValue({});
    renderAdmin();
    const theirs = await screen.findByRole("article", { name: "Ari (@ari)" });
    const toggle = within(theirs).getByRole("button", { name: "Quotas & AI access for @ari" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(within(theirs).getByRole("heading", { name: "Monthly limits" })).toBeInTheDocument();
    fireEvent.change(within(theirs).getByLabelText(/^Chapters/), { target: { value: "50" } });
    await act(async () => fireEvent.click(within(theirs).getByRole("button", { name: "Save limits" })));
    expect(adminApi.updateUser).toHaveBeenCalledWith(2, {
      quota_translated_chapters: 50, quota_ocr_pages: null, quota_codex_builds: null, quota_tts_chapters: null,
    });
    fireEvent.click(within(theirs).getByRole("switch", { name: "OpenAI Codex access" }));
    fireEvent.click(within(theirs).getByRole("checkbox", { name: "Codex batch translation" }));
    await act(async () => fireEvent.click(within(theirs).getByRole("button", { name: "Save AI access" })));
    expect(adminApi.saveAiPolicy).toHaveBeenCalledWith(2, expect.objectContaining({
      openai_codex_enabled: true, openai_codex_workloads: ["translate_batch"], default_backend: "api",
    }));
  });

  it("deletes only after the username is typed", async () => {
    renderAdmin();
    const theirs = await screen.findByRole("article", { name: "Ari (@ari)" });
    fireEvent.click(within(theirs).getByRole("button", { name: "Delete @ari" }));
    const dialog = screen.getByRole("dialog", { name: "Delete @ari?" });
    const confirm = within(dialog).getByRole("button", { name: "Delete user" });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(dialog).getByPlaceholderText("ari"), { target: { value: "ari" } });
    await act(async () => fireEvent.click(confirm));
    expect(adminApi.deleteUser).toHaveBeenCalledWith(2);
  });

  it("routes tabs as /admin/:tab", async () => {
    vi.spyOn(adminApi, "usage").mockResolvedValue({
      totals: { translated_chapters: 249, ocr_pages: 90, codex_builds: 7, active_users: 2 }, user_count: 3, novel_count: 14,
      top_spenders: [{ id: 2, username: "ari", display_name: "Ari", translated_chapters: 34, ocr_pages: 0, codex_builds: 1 }],
      months: [{ period: "2026-08-01", translated_chapters: 200, ocr_pages: 80, codex_builds: 6 }, { period: "2026-09-01", translated_chapters: 240, ocr_pages: 90, codex_builds: 7 }],
    });
    renderAdmin();
    await screen.findByRole("article", { name: "Ari (@ari)" });
    expect(screen.getAllByRole("tab").map(t => t.textContent)).toEqual(ADMIN_TABS.map(t => t.label));
    fireEvent.click(screen.getByRole("tab", { name: "Usage & cost" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/admin/usage");
    expect(await screen.findByText("Chapters translated", { selector: ".adm-metric-label" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Top spenders" })).toBeInTheDocument();
    expect(screen.getByRole("table")).toHaveTextContent("Sep 2026");
  });

  it("changes a novel's visibility from moderation", async () => {
    vi.spyOn(adminApi, "novels").mockResolvedValue([{ id: 9, title: "Moonlit Archive", author: "Sable Ren", visibility: "public", owner_username: "ari", chapter_count: 57 }]);
    vi.spyOn(catalogApi, "setVisibility").mockResolvedValue({});
    renderAdmin("/admin/moderation");
    const select = await screen.findByRole("combobox", { name: "Visibility of Moonlit Archive" });
    await act(async () => fireEvent.change(select, { target: { value: "global" } }));
    expect(catalogApi.setVisibility).toHaveBeenCalledWith(9, "global");
    expect(adminApi.novels).toHaveBeenCalledTimes(2);
  });

  it("runs a global job and reports inline", async () => {
    vi.spyOn(adminApi, "globalNovels").mockResolvedValue([{ id: 3, title: "The Salt Library", chapter_count: 130, source_count: 1, has_raw: false, untranslated: 0, codex_enabled: true, last_scraped_at: null }]);
    vi.spyOn(acquisitionApi, "scrape").mockResolvedValue({});
    renderAdmin("/admin/jobs");
    fireEvent.click(await screen.findByRole("button", { name: "Scrape" }));
    expect(acquisitionApi.scrape).toHaveBeenCalledWith(3, {});
    expect(await screen.findByText("Scrape scheduled.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rebuild codex" })).toBeInTheDocument();
  });

  it("shows worker health and only allows retry when jobs wait", async () => {
    vi.spyOn(adminApi, "agyHealth").mockResolvedValue({
      enabled: true, available: true, worker: { status: "healthy", version: "0.52.0", plugin_version: "1.1.2" },
      queue: { queued: 1, running: 2, waiting_provider: 0 }, last_success_at: null, recent_failures: [{ code: "rate_limited", count: 3 }],
    });
    renderAdmin("/admin/agy");
    expect(await screen.findByRole("heading", { name: /Antigravity\s*Working/ })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /running/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run consuming smoke test" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Retry waiting jobs" })).toBeDisabled();
    expect(screen.getByText("rate_limited")).toBeInTheDocument();
  });
});
