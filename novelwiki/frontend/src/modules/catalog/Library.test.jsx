import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionGlobalConfig } from "motion/react";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { catalogApi } from "./api.js";
import { Library } from "./Library.jsx";
import { ToastProvider } from "../../components/toast.jsx";

const now = new Date().toISOString();
const books = [
  { id: 7, title: "The Glass Tide", author: "Elena Marsh", shelf: "reading", chapter_count: 240, min_chapter: 1, max_chapter: 240, last_chapter: 119, max_chapter_read: 118, last_read_at: now, new_chapters: 6, cover_url: null },
  { id: 8, title: "Letters from the North", author: "Clara Finch", shelf: "to_read", chapter_count: 94, min_chapter: 1, max_chapter: 94, last_chapter: null, max_chapter_read: 0, new_chapters: 0, cover_url: null },
  { id: 9, title: "The Clockwork Sea", author: "Idris Vale", shelf: "completed", chapter_count: 88, min_chapter: 1, max_chapter: 88, last_chapter: 88, max_chapter_read: 88, new_chapters: 0, cover_url: null },
];

function Where() {
  const location = useLocation();
  return <output data-testid="where">{location.pathname}</output>;
}

function renderLibrary() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={["/library"]}>
          <Routes><Route path="*" element={<><Library /><Where /></>} /></Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

const titles = (container) => [...container.querySelectorAll(".shelf-card-title")].map(el => el.textContent);

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
beforeEach(() => { localStorage.clear(); stubMatchMedia(); });

describe("Library", () => {
  it("offers recovery when the library can't load, then shows the shelf", async () => {
    vi.spyOn(catalogApi, "novels")
      .mockRejectedValueOnce(new Error("Temporarily unavailable"))
      .mockResolvedValueOnce([books[0]]);
    const { container } = renderLibrary();
    expect(screen.getByRole("heading", { name: "Library" })).toBeInTheDocument();
    expect(await screen.findByText("Your library couldn't load")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(titles(container)).toEqual(["The Glass Tide"]));
    // cover link, resume link and shelf menu are siblings — nothing interactive nests in a link
    expect(container.querySelectorAll(".shelf-card a button, .shelf-card a a")).toHaveLength(0);
    expect(screen.getByRole("link", { name: "Resume The Glass Tide" })).toHaveAttribute("href", "/n/7/read/119");
  });

  it("shows shelf counts, real summary figures and reading state", async () => {
    vi.spyOn(catalogApi, "novels").mockResolvedValue(books);
    const { container } = renderLibrary();
    await waitFor(() => expect(titles(container)).toHaveLength(3));
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map(t => within(t).queryByText(/^\d+$/)?.textContent)).toEqual(["3", "1", "1", "1"]);
    expect(container.querySelector(".lib-summary")).toHaveTextContent(/3 books on your shelves/);
    expect(container.querySelector(".lib-summary")).toHaveTextContent(/206 chapters read/);
    expect(container.querySelector(".shelf-new")).toHaveTextContent("6 new chapters");
    expect(screen.getByText("Finished")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start reading Letters from the North" })).toHaveAttribute("href", "/n/8/read/1");
  });

  it("filters by shelf and search, persisting the shelf", async () => {
    vi.spyOn(catalogApi, "novels").mockResolvedValue(books);
    const { container } = renderLibrary();
    await waitFor(() => expect(titles(container)).toHaveLength(3));
    fireEvent.click(screen.getByRole("tab", { name: /^Completed/ }));
    await waitFor(() => expect(titles(container)).toEqual(["The Clockwork Sea"]));
    expect(JSON.parse(localStorage.getItem("nw-lib-tab"))).toBe("completed");
    fireEvent.click(screen.getByRole("tab", { name: /^All/ }));
    fireEvent.change(screen.getByRole("textbox", { name: "Search your library" }), { target: { value: "finch" } });
    await waitFor(() => expect(titles(container)).toEqual(["Letters from the North"]));
    expect(container.querySelector(".lib-status")).toHaveTextContent("1 book matching “finch”");
    fireEvent.change(screen.getByRole("textbox", { name: "Search your library" }), { target: { value: "nothing like this" } });
    expect(await screen.findByText("No matches")).toBeInTheDocument();
    // the empty state offers its own way back (the field's × is the other "Clear search")
    fireEvent.click(screen.getAllByRole("button", { name: "Clear search" }).at(-1));
    await waitFor(() => expect(titles(container)).toHaveLength(3));
  });

  it("focuses search with the slash key", async () => {
    vi.spyOn(catalogApi, "novels").mockResolvedValue(books);
    renderLibrary();
    const search = screen.getByRole("textbox", { name: "Search your library" });
    fireEvent.keyDown(document.body, { key: "/" });
    expect(search).toHaveFocus();
  });

  it("moves shelves optimistically with an Undo toast", async () => {
    vi.spyOn(catalogApi, "novels").mockResolvedValue(books);
    const update = vi.spyOn(catalogApi, "updateNovel").mockResolvedValue({});
    const { container } = renderLibrary();
    await waitFor(() => expect(titles(container)).toHaveLength(3));
    const card = [...container.querySelectorAll(".shelf-card")].find(el => el.textContent.includes("The Glass Tide"));
    fireEvent.click(within(card).getByRole("button", { name: "Shelf menu" }));
    fireEvent.click(within(card).getByRole("button", { name: /Completed/ }));
    expect(update).toHaveBeenCalledWith(7, { shelf: "completed" });
    expect(await screen.findByText("Moved to Completed.")).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Undo" })); });
    expect(update).toHaveBeenLastCalledWith(7, { shelf: "reading" });
  });

  it("rolls a failed shelf move back and says why", async () => {
    vi.spyOn(catalogApi, "novels").mockResolvedValue(books);
    vi.spyOn(catalogApi, "updateNovel").mockRejectedValue(new Error("Shelf is read-only"));
    const { container } = renderLibrary();
    await waitFor(() => expect(titles(container)).toHaveLength(3));
    fireEvent.click(screen.getByRole("tab", { name: /^Reading/ }));
    await waitFor(() => expect(titles(container)).toEqual(["The Glass Tide"]));
    const card = container.querySelector(".shelf-card");
    fireEvent.click(within(card).getByRole("button", { name: "Shelf menu" }));
    fireEvent.click(within(card).getByRole("button", { name: /To read/ }));
    expect(await screen.findByText("Shelf is read-only")).toBeInTheDocument();
    await waitFor(() => expect(titles(container)).toEqual(["The Glass Tide"]));
  });

  it("removes from the library with Undo", async () => {
    vi.spyOn(catalogApi, "novels").mockResolvedValue(books);
    vi.spyOn(catalogApi, "removeFromLibrary").mockResolvedValue({});
    const add = vi.spyOn(catalogApi, "addToLibrary").mockResolvedValue({});
    const { container } = renderLibrary();
    await waitFor(() => expect(titles(container)).toHaveLength(3));
    const card = [...container.querySelectorAll(".shelf-card")].find(el => el.textContent.includes("The Clockwork Sea"));
    fireEvent.click(within(card).getByRole("button", { name: "Shelf menu" }));
    fireEvent.click(within(card).getByRole("button", { name: "Remove from library" }));
    await waitFor(() => expect(titles(container)).not.toContain("The Clockwork Sea"));
    expect(await screen.findByText(/Removed “The Clockwork Sea” from your library/)).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Undo" })); });
    expect(add).toHaveBeenCalledWith(9);
  });

  it("switches to the list view and remembers it", async () => {
    vi.spyOn(catalogApi, "novels").mockResolvedValue(books);
    const { container } = renderLibrary();
    await waitFor(() => expect(titles(container)).toHaveLength(3));
    fireEvent.click(screen.getByRole("button", { name: "List" }));
    await waitFor(() => expect(container.querySelectorAll(".lib-row")).toHaveLength(3));
    expect(JSON.parse(localStorage.getItem("nw-lib-view"))).toBe("list");
    expect(container.querySelectorAll(".lib-row a a, .lib-row a button")).toHaveLength(0);
  });

  it("welcomes an empty library with three ways in", async () => {
    vi.spyOn(catalogApi, "novels").mockResolvedValue([]);
    renderLibrary();
    expect(await screen.findByRole("heading", { name: "No novels yet" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Browse shared library/ })).toHaveAttribute("href", "/discover");
    fireEvent.click(screen.getByRole("button", { name: /Import a book/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/import");
  });
});
