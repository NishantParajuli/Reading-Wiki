import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AnswerBody, Markdown } from "./markdown.jsx";

const prose = (container) => container.querySelector(".prose");

describe("codex entry prose citations", () => {
  it("names the chapter a line comes from instead of an internal id", () => {
    const { container } = render(<Markdown text="She arrived before dawn [Chunk 3, Chapter 1]. Then the door [Ch.2, id 7] opened." />);
    const marks = [...container.querySelectorAll(".cite.static")];
    expect(marks.map(m => m.textContent)).toEqual(["ch. 1 (chapter 1)", "ch. 2 (chapter 2)"]);
    expect(marks[0]).toHaveAttribute("title", "Chapter 1");
    expect(prose(container).textContent).not.toMatch(/\b[37]\b/);
  });

  it("drops a marker that names no chapter, without a stray space", () => {
    const { container } = render(<Markdown text="The bells ring by themselves [Chunk 7]. Nobody climbs the tower [Fact 4] anymore." />);
    expect(container.querySelector(".cite.static")).toBeNull();
    expect(prose(container).textContent).toBe("The bells ring by themselves. Nobody climbs the tower anymore.");
  });

  it("resolves facts and relationships through chapterOf, and skips a repeated chapter", () => {
    const chapterOf = (kind, id) => (kind === "fact" && id === "29" ? "12" : kind === "rel" && id === "4" ? "3" : null);
    const { container } = render(
      <Markdown text="Keeps the key [Fact 29] [Chunk 5, Chapter 12]; trusts the Archivist [Rel 4]." chapterOf={chapterOf} />,
    );
    const marks = [...container.querySelectorAll(".cite.static")].map(m => m.getAttribute("title"));
    expect(marks).toEqual(["Chapter 12", "Chapter 3"]);
  });

  it("keeps answers' numbered source buttons", () => {
    const citeMap = { "chunk:3": { ch: 1, quote: "The tide turns.", kind: "chunk", id: 3 } };
    render(<AnswerBody answer="The door opens at dawn [Chunk 3, Chapter 1]." citeMap={citeMap} />);
    expect(screen.getByRole("button", { name: "Source 1, chapter 1" })).toBeInTheDocument();
  });
});
