import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionGlobalConfig } from "motion/react";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { Jobs } from "./Jobs.jsx";
import { JobRow } from "./JobRow.jsx";
import { workApi } from "./api.js";
import { experienceApi } from "../experience/api.js";
import { catalogApi } from "../catalog/api.js";
import { narrationApi } from "../narration/api.js";
import { ToastProvider } from "../../components/toast.jsx";

const now = Date.now();
const iso = (ms) => new Date(now - ms).toISOString();
const running = {
  source: "job", id: 501, kind: "translate", status: "running", novel_id: 7, cancelable: true,
  progress: { done: 12, total: 40 }, created_at: iso(600e3), updated_at: iso(30e3),
};
const narration = {
  source: "tts", id: 77, kind: "tts", status: "queued", novel_id: null, cancelable: true,
  progress: { done: 0, total: 12 }, created_at: iso(60e3), updated_at: iso(60e3),
};
const failedScrape = {
  source: "job", id: 466, kind: "scrape", status: "failed", novel_id: 7, cancelable: false,
  error: "Novelpia requires an ad. Open https://global.novelpia.com/viewer/409763, complete the ad, then retry.",
  created_at: iso(3600e3), updated_at: iso(3000e3), attempts: 1, max_attempts: 3,
};

function renderJobs() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={["/jobs"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Jobs /></MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeAll(() => { MotionGlobalConfig.skipAnimations = true; });
afterAll(() => { MotionGlobalConfig.skipAnimations = false; });
beforeEach(() => {
  vi.spyOn(catalogApi, "novels").mockResolvedValue([{ id: 7, title: "The Glass Tide", author: "Elena Marsh" }]);
});

describe("Jobs", () => {
  it("shows the empty active state with a way forward", async () => {
    vi.spyOn(experienceApi, "activity").mockResolvedValue({ jobs: [] });
    renderJobs();
    expect(screen.getByRole("heading", { name: "Jobs" })).toBeInTheDocument();
    expect(await screen.findByText("No active jobs")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import a book" })).toBeInTheDocument();
    expect(screen.queryByText("Updating live")).not.toBeInTheDocument();
  });

  it("groups active work by novel, shows live progress and cancels through the owning system", async () => {
    vi.spyOn(experienceApi, "activity").mockResolvedValue({ jobs: [running, narration, failedScrape] });
    const cancelJob = vi.spyOn(workApi, "cancelJob").mockResolvedValue({});
    const cancelTts = vi.spyOn(narrationApi, "cancelTtsJob").mockResolvedValue({});
    renderJobs();
    expect(await screen.findByRole("link", { name: "The Glass Tide" })).toHaveAttribute("href", "/n/7");
    expect(screen.getByText("General")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Translation progress" })).toHaveAttribute("aria-valuenow", "30");
    expect(screen.getByText("Updating live")).toBeInTheDocument();
    expect(screen.queryByText("Scrape")).not.toBeInTheDocument();
    const [translateCancel, narrationCancel] = screen.getAllByRole("button", { name: "Cancel" });
    fireEvent.click(translateCancel);
    await waitFor(() => expect(cancelJob).toHaveBeenCalledWith(501));
    fireEvent.click(narrationCancel);
    await waitFor(() => expect(cancelTts).toHaveBeenCalledWith(77));
  });

  it("opens a failed job into a copyable error with Novelpia recovery", async () => {
    vi.spyOn(experienceApi, "activity").mockResolvedValue({ jobs: [failedScrape] });
    const writeText = vi.fn().mockResolvedValue();
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderJobs();
    fireEvent.click(await screen.findByRole("tab", { name: /History/ }));
    const toggle = await screen.findByRole("button", { name: "Show error" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(await screen.findByText(/requires an ad/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open chapter on Novelpia" }))
      .toHaveAttribute("href", "https://global.novelpia.com/viewer/409763");
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(failedScrape.error));
    fireEvent.click(screen.getByRole("button", { name: "Hide error" }));
    await waitFor(() => expect(screen.queryByText(/requires an ad/)).not.toBeInTheDocument());
  });

  it("offers a retry instead of an empty list when jobs can't load", async () => {
    vi.spyOn(experienceApi, "activity")
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue({ jobs: [] });
    renderJobs();
    expect(await screen.findByText("Couldn't load jobs")).toBeInTheDocument();
    expect(screen.queryByText("No active jobs")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No active jobs")).toBeInTheDocument();
  });
});

describe("JobRow", () => {
  it("never describes a finished job as still working", () => {
    render(<JobRow job={{ source: "tts", id: 1, kind: "tts", status: "canceled", cancelable: false, created_at: iso(9000), updated_at: iso(500) }} />);
    expect(screen.getByText("Canceled")).toBeInTheDocument();
    expect(screen.queryByText("narrating…")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("keeps the inline error for callers without a detail panel", () => {
    render(<JobRow job={failedScrape} />);
    expect(screen.getByText(failedScrape.error.slice(0, 60))).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show error" })).not.toBeInTheDocument();
  });
});
