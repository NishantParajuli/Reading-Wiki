import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { paragraphIllustrations, prepareIllustratedHtml } from "./illustrationPlacement.js";
import { NarratedProse } from "./NarratedProse.jsx";
import { RichContent } from "./ReaderParts.jsx";
import { buildPlainNarrationGuide } from "./narrationGuide.js";

vi.mock("../codex/index.js", () => ({ Illustration: ({ item }) => <figure data-scene={item.id}>{item.title}</figure> }));
const scene = (id, position, anchor = "") => ({ id, title: id, placement: { position, anchor } });
const paragraphs = [{ text: "Mira entered the city." }, { text: "The gate closed behind her." }, { text: "It was finally quiet." }];

describe("illustrations between prose blocks", () => {
  it("places opening, middle, and ending scenes without changing narration indices", () => {
    const prepared = buildPlainNarrationGuide(paragraphs.map(p => p.text).join("\n\n"));
    const { container } = render(<NarratedProse prepared={prepared} illustrations={[scene("opening", "start"), scene("gate", "after", "closed behind her"), scene("ending", "end")]} />);
    expect([...container.firstChild.children].map(node => node.tagName)).toEqual(["FIGURE", "P", "P", "FIGURE", "P", "FIGURE"]);
    expect([...container.querySelectorAll("[data-narration-chunk]")].map(node => node.dataset.narrationChunk)).toEqual(["0", "1", "2"]);
  });
  it("omits stale or ambiguous anchors instead of inserting at the wrong moment", () => {
    expect(paragraphIllustrations(paragraphs, [scene("bad", "after", "missing")]).size).toBe(0);
    expect(paragraphIllustrations([{ text: "Mira Mira" }], [scene("ambiguous", "after", "Mira")]).size).toBe(0);
  });
  it("positions quotes spanning paragraphs after their final paragraph", () => {
    const slots = paragraphIllustrations(paragraphs, [scene("cross", "after", "city.\n\nThe gate")]);
    expect(slots.get(2)?.[0].id).toBe("cross");
  });
  it("keeps legacy scenes visible at the end", () => {
    expect(paragraphIllustrations(paragraphs, [{ id: "legacy" }]).get(3)[0].id).toBe("legacy");
  });
  it("matches rich text through formatting while preserving links and narration spans", () => {
    const html = '<p><span data-narration-chunk="0">Mira entered <em>the city</em>.</span></p><p><a href="/map">The gate closed.</a></p>';
    const prepared = prepareIllustratedHtml(html, [scene("city", "after", "entered the city")]);
    const root = document.createElement("div"); root.innerHTML = prepared.html;
    expect(root.children[1].getAttribute("data-illustration-slot")).toBe("0");
    expect(root.querySelector("a").getAttribute("href")).toBe("/map");
    expect(root.querySelector("[data-narration-chunk]").textContent).toBe("Mira entered the city.");
  });
  it("resolves rich quotes across paragraph whitespace and preserves opening order", () => {
    const prepared = prepareIllustratedHtml("<p>Mira smiled. 🌙</p><p>The gate closed.</p>", [scene("first", "start"), scene("second", "start"), scene("cross", "after", "🌙\n\nThe gate")]);
    const root = document.createElement("div"); root.innerHTML = prepared.html;
    expect([...root.querySelectorAll("[data-illustration-slot]")].map(node => node.dataset.illustrationSlot)).toEqual(["0", "1", "2"]);
    expect(root.lastChild.dataset.illustrationSlot).toBe("2");
  });
  it("renders rich illustrations in the chapter and updates after navigation", () => {
    const { container, rerender } = render(<RichContent html="<p>Mira entered the city.</p><p>The gate closed.</p>" illustrations={[scene("city", "after", "entered the city")]} />);
    expect(container.querySelector(".reader-rich").children[1].querySelector("figure").dataset.scene).toBe("city");
    rerender(<RichContent html="<p>Another chapter.</p>" illustrations={[]} />);
    expect(container.querySelector("figure")).toBeNull();
  });
});
