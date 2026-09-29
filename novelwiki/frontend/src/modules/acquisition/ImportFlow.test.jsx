import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OcrProgress, PlanEditor, Stepper, UploadDrop } from "./ImportParts.jsx";

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
