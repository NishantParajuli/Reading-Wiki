import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IllustrationRangePanel } from "./IllustrationRangePanel.jsx";
import { codexApi } from "./api.js";

const ready = { can_generate: true, active_job: null };
const wrap = () => <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><IllustrationRangePanel novelId={7} novel={{ progress: { last_chapter: 25 } }} /></MemoryRouter>;
beforeEach(() => {
  vi.spyOn(codexApi, "illustrationRange").mockResolvedValue(ready);
  vi.spyOn(codexApi, "generateIllustrationRange").mockResolvedValue({ job_id: "range-1", created: true, chapter_count: 76 });
});
afterEach(() => vi.useRealTimers());

describe("illustrate ahead", () => {
  it("queues the selected chapter range with AI count and preserves existing art by default", async () => {
    await act(async () => render(wrap()));
    expect(screen.getByLabelText("From chapter")).toHaveValue(25);
    fireEvent.change(screen.getByLabelText("Through chapter"), { target: { value: "100" } });
    expect(codexApi.generateIllustrationRange).not.toHaveBeenCalled();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Illustrate chapters" })));
    expect(codexApi.generateIllustrationRange).toHaveBeenCalledWith(7, { from_chapter: 25, to_chapter: 100, style: "luminous", force: false });
    expect(screen.getByRole("button", { name: "Illustrate chapters" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "View progress in Jobs" })).toHaveAttribute("href", "/jobs");
  });
  it("rejects an inverted range without starting work", async () => {
    await act(async () => render(wrap()));
    fireEvent.change(screen.getByLabelText("Through chapter"), { target: { value: "24" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Illustrate chapters" })));
    expect(screen.getByRole("alert")).toHaveTextContent("final chapter at or after the first");
    expect(codexApi.generateIllustrationRange).not.toHaveBeenCalled();
  });
  it("allows an explicit style replacement and reports provider waits", async () => {
    vi.useFakeTimers();
    await act(async () => render(wrap()));
    fireEvent.change(screen.getByLabelText("Through chapter"), { target: { value: "100" } });
    fireEvent.change(screen.getByLabelText("Art style"), { target: { value: "ink" } });
    fireEvent.click(screen.getByRole("checkbox"));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Illustrate chapters" })));
    expect(codexApi.generateIllustrationRange).toHaveBeenCalledWith(7, { from_chapter: 25, to_chapter: 100, style: "ink", force: true });
    codexApi.illustrationRange.mockResolvedValue({ ...ready, active_job: { status: "waiting_provider" } });
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(screen.getByRole("status")).toHaveTextContent("Waiting for image generation");
    codexApi.illustrationRange.mockResolvedValue({ ...ready, active_job: { status: "done" } });
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(screen.getByRole("status")).toHaveTextContent("Illustrations are ready");
    await act(async () => vi.advanceTimersByTimeAsync(10000));
    expect(codexApi.illustrationRange).toHaveBeenCalledTimes(3);
  });
  it("shows unavailable access without enabling generation", async () => {
    codexApi.illustrationRange.mockResolvedValue({ can_generate: false, unavailable_reason: "Connect a Codex account first." });
    await act(async () => render(wrap()));
    expect(screen.getByText("Connect a Codex account first.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Illustrate chapters" })).toBeDisabled();
  });
});
