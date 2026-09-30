import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionGlobalConfig } from "motion/react";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { catalogApi } from "./api.js";
import { Discover } from "./Discover.jsx";
import { experienceApi } from "../experience/api.js";
import { ToastProvider } from "../../components/toast.jsx";

const shared = [
  { id: 11, title: "The Salt Library", author: "Wren Halloway", description: "A library that only opens at low tide.", has_codex: true, has_audio: true, translation_type: "translated", language: "en", chapter_count: 130, owner_username: "archivist" },
  { id: 7, title: "The Glass Tide", author: "Elena Marsh", description: null, has_codex: true, has_audio: false, translation_type: null, language: "en", chapter_count: 240, owner_username: "archivist" },
  { id: 12, title: "Emberfall", author: "Oren Blackwood", has_codex: false, has_audio: false, translation_type: "raws+translated", language: "ko", chapter_count: 764, owner_username: "archivist" },
  { id: 13, title: "The Hollow Bell", author: "Mara Quill", has_codex: false, has_audio: false, translation_type: null, language: "en", chapter_count: 45, owner_username: "archivist" },
];

function Where() {
  const location = useLocation();
  return <output data-testid="where">{location.pathname + location.search}</output>;
}

function renderDiscover(route = "/discover") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={[route]}>
          <Routes><Route path="*" element={<><Discover /><Where /></>} /></Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

/* A plain matchMedia: the shared setup's vi.fn() stub is reset by restoreMocks,
   and motion's reduced-motion probe needs a real object. */
function stubMatchMedia() {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; },
  });
}

beforeAll(() => { MotionGlobalConfig.skipAnimations = true; });
afterAll(() => { MotionGlobalConfig.skipAnimations = false; });
beforeEach(() => { stubMatchMedia(); });

describe("Discover", () => {
  it("sets the first stories as a featured strip over the shared shelf", async () => {
    vi.spyOn(experienceApi, "discover").mockResolvedValue({ items: shared, total: 4, offset: 0, limit: 60 });
    renderDiscover();
    expect(screen.getByRole("heading", { name: "Discover" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "The Salt Library" })).toBeInTheDocument();
    expect(screen.getByText("A library that only opens at low tide.")).toBeInTheDocument();
    expect(screen.getAllByText("The Glass Tide").length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "More to explore" })).toBeInTheDocument();
    expect(document.querySelectorAll(".shelf-card a button, .shelf-card a a")).toHaveLength(0);
  });

  it("adds optimistically, flips to In library and offers Open", async () => {
    vi.spyOn(experienceApi, "discover").mockResolvedValue({ items: shared, total: 4, offset: 0, limit: 60 });
    const add = vi.spyOn(catalogApi, "addToLibrary").mockResolvedValue({});
    renderDiscover();
    fireEvent.click(await screen.findByRole("button", { name: "Add The Hollow Bell to library" }));
    expect(add).toHaveBeenCalledWith(13);
    expect(screen.getByRole("button", { name: "In library" })).toHaveAttribute("aria-disabled", "true");
    expect(await screen.findByText("Added “The Hollow Bell” to your library.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/n/13");
  });

  it("rolls a failed add back with the reason", async () => {
    vi.spyOn(experienceApi, "discover").mockResolvedValue({ items: shared, total: 4, offset: 0, limit: 60 });
    vi.spyOn(catalogApi, "addToLibrary").mockRejectedValue(new Error("Library is full"));
    renderDiscover();
    fireEvent.click(await screen.findByRole("button", { name: "Add The Salt Library to library" }));
    expect(await screen.findByText("Library is full")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add The Salt Library to library" })).not.toHaveAttribute("aria-disabled");
  });

  it("mirrors filters and the debounced search in the URL", async () => {
    const discover = vi.spyOn(experienceApi, "discover").mockResolvedValue({ items: shared, total: 4, offset: 0, limit: 60 });
    renderDiscover("/discover?lang=ko");
    await screen.findByRole("link", { name: "Emberfall" });
    expect(discover).toHaveBeenLastCalledWith(expect.objectContaining({ language: "ko", offset: 0, limit: 60 }));
    fireEvent.click(screen.getByRole("button", { name: "Has codex" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("codex=1"));
    await waitFor(() => expect(discover).toHaveBeenLastCalledWith(expect.objectContaining({ has_codex: true, language: "ko" })));
    // desktop pill × and the phone's active-filter chip (CSS shows one per breakpoint)
    expect(screen.getAllByRole("button", { name: "Clear Language" })).toHaveLength(2);
    fireEvent.click(screen.getAllByRole("button", { name: "Clear Language" })[0]);
    await waitFor(() => expect(screen.getByTestId("where")).not.toHaveTextContent("lang="));
    fireEvent.change(screen.getByRole("textbox", { name: "Search the shared library" }), { target: { value: "salt" } });
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("q=salt"));
    await waitFor(() => expect(discover).toHaveBeenLastCalledWith(expect.objectContaining({ q: "salt", has_codex: true })));
  });

  it("offers filters as real menus: grouped choices, the current one checked", async () => {
    vi.spyOn(experienceApi, "discover").mockResolvedValue({ items: shared, total: 4, offset: 0, limit: 60 });
    renderDiscover("/discover?tag=fantasy");
    await screen.findByRole("link", { name: "Emberfall" });
    const language = screen.getByRole("button", { name: "Language" });
    expect(language).toHaveAttribute("aria-haspopup", "menu");
    fireEvent.click(language);
    const menu = screen.getByRole("menu", { name: "Language" });
    expect(within(menu).getAllByRole("menuitemradio").map(el => el.textContent)).toEqual(["English", "Japanese", "Korean", "Chinese"]);
    expect(within(menu).getAllByRole("menuitemradio")[0]).toHaveFocus();
    fireEvent.click(within(menu).getByRole("menuitemradio", { name: "Korean" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("lang=ko"));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(language).toHaveFocus();
    // the grouped genre menu names its groups and checks the active tag
    fireEvent.click(screen.getByRole("button", { name: /^Genre:/ }));
    const genre = screen.getByRole("menu", { name: "Genre" });
    expect(within(genre).getByRole("group", { name: "Genre" })).toBeInTheDocument();
    const fantasy = within(genre).getByRole("menuitemradio", { name: "Fantasy" });
    expect(fantasy).toHaveAttribute("aria-checked", "true");
    expect(fantasy).toHaveFocus();
  });

  it("pages with Load more and shows the totals", async () => {
    const page2 = [{ id: 21, title: "Tidewrights", author: "Pell Aurin", chapter_count: 210 }];
    const discover = vi.spyOn(experienceApi, "discover")
      .mockResolvedValueOnce({ items: shared, total: 5, offset: 0, limit: 60 })
      .mockResolvedValueOnce({ items: page2, total: 5, offset: 4, limit: 60 });
    renderDiscover("/discover?sort=title");
    expect(await screen.findByText("Showing", { exact: false })).toHaveTextContent("Showing 4 of 5");
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByRole("link", { name: "Tidewrights" })).toBeInTheDocument();
    expect(discover).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 4, sort: "title" }));
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("says so honestly when the shared library is unavailable, and recovers", async () => {
    vi.spyOn(experienceApi, "discover")
      .mockRejectedValueOnce(new Error("Unavailable"))
      .mockResolvedValueOnce({ items: shared, total: 4, offset: 0, limit: 60 });
    renderDiscover();
    expect(await screen.findByText("The shared library couldn't load")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "The Salt Library" })).toBeInTheDocument();
  });

  it("offers a way out when nothing matches", async () => {
    vi.spyOn(experienceApi, "discover").mockResolvedValue({ items: [], total: 0, offset: 0, limit: 60 });
    renderDiscover("/discover?q=zzz&codex=1");
    expect(await screen.findByText("Nothing matches — yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Clear search & filters/ }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(/^\/discover$/));
  });
});
