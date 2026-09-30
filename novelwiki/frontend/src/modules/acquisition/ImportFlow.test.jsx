import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { catalogApi } from "../catalog/api.js";
import { JobHeader, OcrProgress, PlanEditor, Stepper, UploadDrop } from "./ImportParts.jsx";

const plan = {
  version: 1,
  segments: [
    { id: "a", title: "Chapter 1", kind: "chapter", number: 1, include: true, block_range: [0, 9], word_count: 1200 },
    { id: "b", title: "Chapter 2", kind: "chapter", number: null, include: true, block_range: [10, 19], word_count: 900 },
  ],
};
const metadata = { title: "A quiet sea", author: "", description: "", language: "en", series: "", series_index: "", volume_label: "" };

describe("import tideline", () => {
  it("marks finished steps and says whose turn it is", () => {
    render(<Stepper job={{ status: "awaiting_review" }} />);
    const steps = within(screen.getByRole("list", { name: "Import progress" })).getAllByRole("listitem");
    const spoken = step => [...step.childNodes].filter(node => node.getAttribute("aria-hidden") !== "true").map(node => node.textContent).join("");
    expect(steps.map(spoken)).toEqual(["Upload (done)", "Parse (done)", "Review (waiting for you)", "Commit"]);
    expect(steps[2]).toHaveAttribute("aria-current", "step");
  });

  it("adds the OCR step for scanned books and shows work in progress", () => {
    render(<Stepper job={{ status: "ocr_running" }} />);
    const current = screen.getByRole("listitem", { current: "step" });
    expect(current).toHaveTextContent("OCR (in progress)");
  });
});

describe("OCR progress", () => {
  it("reports pages read as a progressbar and explains a paused budget", () => {
    render(<OcrProgress job={{ status: "ocr_paused", progress: { done: 78, total: 312 } }} />);
    expect(screen.getByRole("progressbar", { name: "OCR progress" })).toHaveAttribute("aria-valuenow", "25");
    expect(screen.getByText("78/312 pages")).toBeInTheDocument();
    expect(screen.getByText(/resumes automatically tomorrow/)).toBeInTheDocument();
  });
});

describe("review editor", () => {
  function renderEditor(props = {}) {
    const onCommit = vi.fn();
    render(
      <PlanEditor job={{ id: 3, options: {}, _novels: [{ id: 9, title: "The Glass Tide", can_edit: true }] }}
                  plan={plan} setPlan={vi.fn()} metadata={metadata} setMetadata={vi.fn()}
                  onSave={vi.fn()} onCommit={onCommit} busy={false} {...props} />,
    );
    return { onCommit };
  }

  it("summarises the destination next to Commit and flags unnumbered chapters", () => {
    renderEditor();
    expect(screen.getByRole("button", { name: /Destination/ })).toHaveTextContent("New novel");
    expect(screen.getByText("1 unnumbered chapter")).toBeInTheDocument();
    expect(screen.getByText("2 will be imported · 2,100 words")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Append to…" }));
    expect(screen.getByRole("button", { name: /Destination/ })).toHaveTextContent("Append to… choose a novel");
    expect(screen.getByRole("button", { name: "Commit" })).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Destination novel" }), { target: { value: "9" } });
    expect(screen.getByRole("button", { name: /Destination/ })).toHaveTextContent("Append to The Glass Tide");
    expect(screen.getByRole("button", { name: "Commit" })).toBeEnabled();
  });

  it("asks before replacing a source's chapters", async () => {
    vi.spyOn(catalogApi, "novel").mockResolvedValue({ id: 9, sources: [{ id: 12, label: "Royal Road", adapter: "royalroad" }] });
    const { onCommit } = renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "Replace…" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Destination novel" }), { target: { value: "9" } });
    await screen.findByRole("option", { name: "Royal Road (#12)" });
    fireEvent.change(screen.getByRole("combobox", { name: "Source to replace" }), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Replace chapters" }));
    const dialog = screen.getByRole("dialog", { name: "Replace this source's chapters?" });
    expect(dialog).toHaveTextContent("Royal Road (#12) in The Glass Tide");
    expect(onCommit).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(onCommit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Replace chapters" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Replace chapters" }));
    expect(onCommit).toHaveBeenCalledWith({ mode: "replace", source_id: 12, offset: 0, is_raw: false, as_volume: false });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("import header", () => {
  it("titles a book by its filename without the extension", () => {
    render(<JobHeader job={{ id: 4, status: "failed", filename: "tidal-atlas_vol_07_FINAL.epub", detected_meta: {} }} meta={{}} />);
    expect(screen.getByRole("heading", { level: 2, name: "tidal-atlas_vol_07_FINAL" })).toBeInTheDocument();
    expect(screen.getByText("tidal-atlas_vol_07_FINAL.epub")).toHaveAttribute("title", "tidal-atlas_vol_07_FINAL.epub");
  });
});

describe("glass basin", () => {
  it("invites the drop while files hover over it", () => {
    render(<UploadDrop onUploaded={vi.fn()} />);
    const basin = screen.getByRole("button", { name: "Choose EPUB or PDF books" });
    expect(basin).toHaveTextContent("Drop your books here, or choose files");
    fireEvent.dragOver(basin);
    expect(basin).toHaveTextContent("Release to add your books");
    fireEvent.dragLeave(basin, { relatedTarget: document.body });
    expect(basin).toHaveTextContent("Drop your books here, or choose files");
  });
});
