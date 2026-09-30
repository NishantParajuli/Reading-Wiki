import React from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { NovelJobs } from "./ManagePanels.jsx";
import { workApi } from "../work/api.js";
import { ToastProvider } from "../../components/toast.jsx";

const at = new Date().toISOString();
const job = (id, status, kind = "translate") => ({ id, kind, status, novel_id: 1, created_at: at, updated_at: at });

function renderJobs() {
  return render(
    <ToastProvider>
      <MemoryRouter><NovelJobs novelId={1} /></MemoryRouter>
    </ToastProvider>,
  );
}

describe("Manage → background jobs", () => {
  it("counts running, queued and waiting jobs separately", async () => {
    vi.spyOn(workApi, "jobs").mockResolvedValue({ jobs: [
      job(1, "running"), job(2, "queued", "codex_build"), job(3, "queued", "scrape"),
      job(4, "waiting_provider", "codex_illustrate"), job(5, "done", "scrape"),
    ] });
    renderJobs();
    expect(await screen.findByText("1 running · 2 queued · 1 waiting")).toBeInTheDocument();
  });

  it("says nothing is active when only finished jobs remain", async () => {
    vi.spyOn(workApi, "jobs").mockResolvedValue({ jobs: [job(5, "done", "scrape")] });
    const { container } = renderJobs();
    await vi.waitFor(() => expect(container.querySelector(".mc-joblist")).not.toBeNull());
    expect(container.querySelector(".mc-live")).toBeNull();
  });
});
