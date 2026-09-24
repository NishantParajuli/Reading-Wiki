import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ImportView } from "./ImportView.jsx";
import { acquisitionApi } from "./api.js";
import { catalogApi } from "../catalog/api.js";

vi.mock("../../App.jsx", () => ({ useAuth: () => ({ user: { role: "reader" } }) }));
const reviewJob = {
  id: 5, filename: "sea.epub", status: "awaiting_review", detected_meta: { title: "A quiet sea" },
  plan: { segments: [{ id: "one", title: "Chapter 1", kind: "chapter", number: 1, include: true, block_range: [0, 1] }] },
};

beforeEach(() => {
  vi.spyOn(catalogApi, "novels").mockResolvedValue([]);
  vi.spyOn(acquisitionApi, "importJobs").mockResolvedValue([reviewJob]);
  vi.spyOn(acquisitionApi, "updateImportPlan").mockResolvedValue({});
});

async function openImport(job = reviewJob) {
  vi.spyOn(acquisitionApi, "importJob").mockResolvedValue(job);
  const result = render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><ImportView /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: /A quiet sea Ready to review/ }));
  return result;
}

describe("import workflow recovery", () => {
  it("refreshes the selected job after committing without requiring reselection", async () => {
    vi.spyOn(acquisitionApi, "commitImport").mockResolvedValue({});
    await openImport();
    await screen.findByRole("button", { name: "Commit" });
    acquisitionApi.importJob.mockResolvedValue({ ...reviewJob, status: "committed", novel_id: 88 });
    fireEvent.click(screen.getByRole("button", { name: "Commit" }));
    await screen.findByText("Imported into your library.");
    expect(acquisitionApi.importJob).toHaveBeenCalledTimes(2);
  });

  it("refreshes after OCR is approved", async () => {
    vi.spyOn(acquisitionApi, "confirmOcr").mockResolvedValue({});
    await openImport({ ...reviewJob, status: "awaiting_ocr_confirm" });
    await screen.findByRole("button", { name: "Run OCR" });
    acquisitionApi.importJob.mockResolvedValue(reviewJob);
    fireEvent.click(screen.getByRole("button", { name: "Run OCR" }));
    await screen.findByRole("button", { name: "Commit" });
    expect(acquisitionApi.importJob).toHaveBeenCalledTimes(2);
  });

  it("does not expose the previous plan while another import is loading", async () => {
    acquisitionApi.importJobs.mockResolvedValue([reviewJob, { ...reviewJob, id: 6, filename: "next.epub", detected_meta: { title: "Next book" } }]);
    await openImport();
    await screen.findByRole("button", { name: "Commit" });
    acquisitionApi.importJob.mockImplementation(() => new Promise(() => {}));
    fireEvent.click(screen.getByRole("button", { name: /Next book Ready to review/ }));
    expect(screen.queryByRole("button", { name: "Commit" })).not.toBeInTheDocument();
    expect(screen.getByText("Opening import…")).toBeInTheDocument();
  });
  it("cannot commit retained review data under a newly selected series volume", async () => {
    const next = { ...reviewJob, id: 6, detected_meta: { title: "Next book" } };
    acquisitionApi.importJobs.mockResolvedValue([reviewJob, next]);
    vi.spyOn(acquisitionApi, "commitSeries").mockResolvedValue({});
    await openImport();
    await screen.findByRole("button", { name: "Commit" });
    fireEvent.click(screen.getByRole("checkbox", { name: "Select A quiet sea for a series" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Next book for a series" }));
    let resolveNext;
    acquisitionApi.importJob.mockImplementation(() => new Promise(resolve => { resolveNext = resolve; }));
    fireEvent.click(screen.getByRole("button", { name: /Next book Ready to review/ }));
    const series = screen.getByRole("button", { name: "Commit as series" });
    expect(series).toBeDisabled();
    fireEvent.click(series);
    expect(acquisitionApi.updateImportPlan).not.toHaveBeenCalled();
    expect(acquisitionApi.commitSeries).not.toHaveBeenCalled();
    await act(async () => { resolveNext(next); });
    expect(series).toBeEnabled();
    fireEvent.click(series);
    await waitFor(() => expect(acquisitionApi.commitSeries).toHaveBeenCalledWith([5, 6], null));
    expect(acquisitionApi.updateImportPlan).toHaveBeenCalledWith(6, expect.anything(), expect.objectContaining({ title: "Next book" }));
  });

});
