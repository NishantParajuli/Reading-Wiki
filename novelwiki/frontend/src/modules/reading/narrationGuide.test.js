import { describe, expect, it } from "vitest";

import {
  activeNarrationChunk,
  buildPlainNarrationGuide,
  buildRichNarrationGuide,
  splitNarrationChunks,
} from "./narrationGuide.js";

describe("narration reading guide", () => {
  it("groups prose into at most two sentences without changing its text", () => {
    const text = "First sentence. Second sentence! Third sentence? Fourth sentence.";
    const chunks = splitNarrationChunks(text);

    expect(chunks).toHaveLength(2);
    expect(chunks.join("")).toBe(text);
    expect(chunks[0]).toContain("Second sentence!");
    expect(chunks[1]).toContain("Fourth sentence.");
  });

  it("builds unique, sequential markers across plain paragraphs", () => {
    const guide = buildPlainNarrationGuide(
      "One. Two. Three.\n  \nA much longer final paragraph without punctuation",
    );

    expect(guide.paragraphs).toHaveLength(2);
    expect(guide.chunks.map(chunk => chunk.index)).toEqual([0, 1, 2]);
    expect(guide.chunks.map(chunk => chunk.sourceIndex)).toEqual([0, 0, 1]);
    expect(guide.paragraphs.flatMap(paragraph => paragraph.chunks).map(chunk => chunk.text).join(""))
      .toBe("One. Two. Three.A much longer final paragraph without punctuation");
  });

  it("preserves rich markup while marking sentence text across inline elements", () => {
    const guide = buildRichNarrationGuide(
      '<p>The <em>first sentence.</em> The second sentence!</p><figure><img src="/cover.jpg"><figcaption>A caption.</figcaption></figure>',
      "The first sentence. The second sentence!\n\nA caption.",
    );
    const template = document.createElement("template");
    template.innerHTML = guide.html;

    expect(template.content.querySelector("em").textContent).toBe("first sentence.");
    expect(template.content.querySelector("img").getAttribute("src")).toBe("/cover.jpg");
    expect(template.content.querySelectorAll("[data-narration-chunk]").length).toBeGreaterThan(2);
    expect(guide.chunks.map(chunk => chunk.index)).toEqual([0, 1]);
    expect(template.content.textContent).toBe("The first sentence. The second sentence!A caption.");
  });

  it("uses actual paragraph boundaries and only estimates within that paragraph", () => {
    const chunks = [
      { index: 0, sourceIndex: 0, weight: 10 },
      { index: 1, sourceIndex: 0, weight: 30 },
      { index: 2, sourceIndex: 1, weight: 10 },
    ];
    const timing = {
      version: 1,
      duration_ms: 110_000,
      paragraphs: [
        { source_index: null, start_ms: 0, speech_end_ms: 4_000, end_ms: 4_350 },
        { source_index: 0, start_ms: 4_350, speech_end_ms: 100_000, end_ms: 100_350 },
        { source_index: 1, start_ms: 100_350, speech_end_ms: 110_000, end_ms: 110_000 },
      ],
    };

    expect(activeNarrationChunk(chunks, 2, timing)).toBeNull();
    expect(activeNarrationChunk(chunks, 10, timing)).toBe(0);
    expect(activeNarrationChunk(chunks, 95, timing)).toBe(1);
    expect(activeNarrationChunk(chunks, 105, timing)).toBe(2);
  });

  it("does not guess for legacy audio without timing metadata", () => {
    const chunks = [{ index: 0, sourceIndex: 0, weight: 10 }];
    expect(activeNarrationChunk(chunks, 5, null)).toBeNull();
  });
});
