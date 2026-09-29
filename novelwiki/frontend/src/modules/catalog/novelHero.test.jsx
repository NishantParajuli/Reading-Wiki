import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HeroFacts, Tideline, fmtNum, languageName, titleScale } from "./NovelHeroParts.jsx";

const novel = {
  id: 1, title: "The Glass Tide", chapter_count: 240, min_chapter: 1, max_chapter: 240,
  original_language: "ja", translation_type: "translated", visibility: "private",
  progress: { last_chapter: 119, max_chapter_read: 118 },
};

describe("novel hero parts", () => {
  it("formats figures and names honestly", () => {
    expect(fmtNum(1432)).toBe((1432).toLocaleString());
    expect(fmtNum(12.5)).toBe("12.5");
    expect(languageName("ja")).toBe("Japanese");
    expect(titleScale("The Glass Tide")).toBe("t-xl");
    expect(titleScale("I Was Reincarnated as the Villainess's Younger Brother but the Northern Duke Keeps Mistaking Me")).toBe("t-sm");
  });

  it("lays out the spec strip from real fields only", () => {
    render(<HeroFacts novel={novel} />);
    expect(screen.getByText("Japanese")).toBeInTheDocument();
    expect(screen.getByText("Translated")).toBeInTheDocument();
    expect(screen.getByText("Private")).toBeInTheDocument();
    render(<HeroFacts novel={{ ...novel, original_language: null, translation_type: null, visibility: null }} />);
    expect(screen.getAllByText("Chapters")).toHaveLength(2);
    expect(screen.getAllByText("Language")).toHaveLength(1);
  });

  it("reports reading progress, your place and bookmarks on the tideline", () => {
    render(<Tideline novel={novel} bookmarks={[{ id: 1, chapter: 42 }, { id: 2, chapter: 117, note: "The door opens" }]} toc={[]} />);
    const bar = screen.getByRole("progressbar", { name: "Reading progress" });
    expect(bar).toHaveAttribute("aria-valuenow", "49");
    expect(bar.getAttribute("aria-valuetext")).toMatch(/49% read · 122 new since you last read\. You are at chapter 119 of 240\. 2 bookmarks\./);
    expect(screen.getByText("49% read · 122 new since you last read")).toBeInTheDocument();
  });

  it("says a book hasn't been started instead of inventing progress", () => {
    render(<Tideline novel={{ ...novel, progress: { last_chapter: null, max_chapter_read: null } }} bookmarks={[]} toc={[]} />);
    expect(screen.getByText("Not started yet")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Reading progress" })).toHaveAttribute("aria-valuenow", "0");
  });
});
