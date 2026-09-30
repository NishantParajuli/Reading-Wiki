import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Profile } from "./Profile.jsx";
import { identityApi } from "./api.js";

vi.mock("../../App.jsx", () => ({ useAuth: () => ({ user: { id: 1, username: "nishant" } }), useTheme: () => ({}) }));

class InstantObserver {
  constructor(cb) { this.cb = cb; }
  observe(target) { this.cb([{ isIntersecting: true, intersectionRatio: 1, target }], this); }
  unobserve() {}
  disconnect() {}
}

const profile = {
  username: "nishant", display_name: "Nishant", role: "admin", bio: "Night reader.", avatar_url: null,
  created_at: "2025-08-01T00:00:00Z", is_self: true,
  stats: { library_count: 10, reading_count: 5, completed_count: 2, chapters_read: 1388 },
  currently_reading: [{ id: 1, title: "The Glass Tide", cover_url: null, last_chapter: 119, max_chapter: 240 }],
  recently_finished: [{ id: 3, title: "The Cartographer's Daughter", cover_url: null }],
  published: [{ id: 4, title: "Letters from the North", cover_url: null, chapter_count: 94, visibility: "public" }],
};

function renderProfile() {
  return render(
    <MemoryRouter initialEntries={["/u/nishant"]}>
      <Routes><Route path="/u/:username" element={<Profile />} /></Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  globalThis.IntersectionObserver = InstantObserver;
  window.matchMedia.mockImplementation((query) => ({
    matches: query.includes("prefers-reduced-motion") && !query.includes("no-preference"), media: query, onchange: null,
    addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
  }));
});

describe("Public profile", () => {
  it("shows a loading state, then the hero, real stats and shelves", async () => {
    vi.spyOn(identityApi, "profile").mockResolvedValue(profile);
    renderProfile();
    expect(screen.getByRole("status")).toHaveTextContent("Loading profile");
    expect(await screen.findByRole("heading", { level: 1, name: "Nishant" })).toBeInTheDocument();
    expect(screen.getByText("@nishant")).toBeInTheDocument();
    expect(screen.getByText("Night reader.")).toBeInTheDocument();
    expect(screen.getByText("Chapters read").nextElementSibling).toHaveTextContent("1,388");
    for (const title of ["Currently reading", "Recently finished", "Published by you"]) {
      expect(screen.getByRole("heading", { level: 2, name: title })).toBeInTheDocument();
    }
    expect(screen.getAllByText("Ch. 119 of 240").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Account & settings" })).toBeInTheDocument();
  });

  it("shows shelf books at once under reduced motion, without waiting for a scroll", async () => {
    globalThis.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
    vi.spyOn(identityApi, "profile").mockResolvedValue(profile);
    renderProfile();
    const shelf = await screen.findByRole("region", { name: "Recently finished" });
    const cell = shelf.querySelector(".pf-book-cell");
    expect(cell).not.toBeNull();
    expect(cell.style.opacity).not.toBe("0");
  });

  it("offers recovery when the profile can't load", async () => {
    vi.spyOn(identityApi, "profile").mockRejectedValueOnce(new Error("User not found.")).mockResolvedValue(profile);
    renderProfile();
    expect(await screen.findByText("Profile unavailable")).toBeInTheDocument();
    expect(screen.getByText("User not found.")).toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Try again" })));
    expect(await screen.findByRole("heading", { level: 1, name: "Nishant" })).toBeInTheDocument();
    expect(identityApi.profile).toHaveBeenCalledTimes(2);
  });

  it("says so honestly when there is no public activity", async () => {
    vi.spyOn(identityApi, "profile").mockResolvedValue({
      ...profile, is_self: false, role: null, currently_reading: [], recently_finished: [], published: [],
    });
    renderProfile();
    expect(await screen.findByText("No public activity yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Account & settings" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Browse Discover" })).toBeInTheDocument();
  });
});
