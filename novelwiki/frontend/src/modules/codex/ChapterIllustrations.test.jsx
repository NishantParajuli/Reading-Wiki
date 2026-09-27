import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChapterIllustrations } from "./ChapterIllustrations.jsx";
import { codexApi } from "./api.js";

const empty = { items: [], can_generate: true, active_job: null };
const art = { id: "scene-1", kind: "scene", title: "The glass shore", caption: "Mira watches the tide.", style: "luminous", image_url: "/api/novels/1/illustrations/scene-1/image" };
const wrap = (chapter = 1) => <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><ChapterIllustrations novelId={1} chapter={chapter} /></MemoryRouter>;
const open = async () => { await act(async () => fireEvent.click(screen.getByRole("button", { name: /Illustrate this chapter/ }))); };

beforeEach(() => {
  vi.spyOn(codexApi, "illustrations").mockResolvedValue(empty);
  vi.spyOn(codexApi, "generateIllustrations").mockResolvedValue({ job_id: "job-1" });
});
afterEach(() => vi.useRealTimers());

describe("chapter illustrations", () => {
  it("loads on demand and never starts generation without an explicit action", async () => {
    render(wrap());
    expect(codexApi.illustrations).not.toHaveBeenCalled();
    await open();
    expect(codexApi.illustrations).toHaveBeenCalledWith(1, 1);
    expect(screen.getByLabelText("Scenes")).toHaveValue("1");
    expect(screen.getByLabelText("Art style")).toHaveValue("luminous");
    expect(codexApi.generateIllustrations).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Scenes"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Art style"), { target: { value: "ink" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Generate illustrations" })));
    expect(codexApi.generateIllustrations).toHaveBeenCalledWith(1, 1, { count: 3, style: "ink", force: false });
    expect(screen.getByRole("button", { name: "Generate illustrations" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "View jobs" })).toHaveAttribute("href", "/jobs");
  });

  it("polls only active jobs and stops after completed artwork arrives", async () => {
    vi.useFakeTimers();
    codexApi.illustrations.mockResolvedValueOnce({ ...empty, active_job: { id: "job-1", status: "running", progress: { stage: "Designing Mira" } } }).mockResolvedValue({ ...empty, items: [art] });
    render(wrap());
    await open();
    expect(screen.getByRole("status")).toHaveTextContent("Designing Mira");
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(codexApi.illustrations).toHaveBeenCalledTimes(2);
    expect(screen.getByText("The glass shore")).toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(15000));
    expect(codexApi.illustrations).toHaveBeenCalledTimes(2);
    expect(codexApi.generateIllustrations).not.toHaveBeenCalled();
  });

  it("discards late results on chapter navigation and keeps the next gallery closed", async () => {
    let finish;
    codexApi.illustrations.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const { rerender } = render(wrap(9));
    await open();
    rerender(wrap(1));
    await act(async () => finish({ ...empty, items: [{ ...art, title: "A future identity" }] }));
    expect(screen.queryByText("A future identity")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Illustrate this chapter/ })).toHaveAttribute("aria-expanded", "false");
    await open();
    expect(codexApi.illustrations).toHaveBeenLastCalledWith(1, 1);
  });

  it("recovers from a list failure without accidentally spending on generation", async () => {
    codexApi.illustrations.mockRejectedValueOnce(new Error("Connection lost"));
    render(wrap());
    await open();
    expect(screen.getByRole("alert")).toHaveTextContent("Connection lost");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Refresh illustrations" })));
    expect(screen.getByRole("button", { name: "Generate illustrations" })).toBeEnabled();
    expect(codexApi.generateIllustrations).not.toHaveBeenCalled();
  });

  it("keeps artwork visible when generation is unavailable and explains why", async () => {
    codexApi.illustrations.mockResolvedValue({ ...empty, can_generate: false, unavailable_reason: "Only the owner can generate illustrations.", items: [art, { ...art, id: "reference-1", title: "Mira", kind: "reference" }] });
    render(wrap());
    await open();
    expect(screen.getByText("The glass shore")).toBeInTheDocument();
    expect(screen.getByText("Character reference sheets")).toBeInTheDocument();
    expect(screen.getByText("Only the owner can generate illustrations.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate illustrations" })).not.toBeInTheDocument();
  });

  it("preserves a completed gallery when a requested regeneration fails", async () => {
    codexApi.illustrations.mockResolvedValue({ ...empty, items: [art] });
    codexApi.generateIllustrations.mockRejectedValue(new Error("Codex is unavailable"));
    render(wrap());
    await open();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Generate again" })));
    expect(codexApi.generateIllustrations).toHaveBeenCalledWith(1, 1, { count: 1, style: "luminous", force: true });
    expect(screen.getByRole("alert")).toHaveTextContent("Codex is unavailable");
    expect(screen.getByText("The glass shore")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate again" })).toBeEnabled();
  });

  it("shows only the chosen style and does not force regeneration for an unillustrated style", async () => {
    codexApi.illustrations.mockResolvedValue({ ...empty, items: [art, { ...art, id: "ink-1", title: "Ink shore", style: "ink" }] });
    render(wrap());
    await open();
    expect(screen.getByText("The glass shore")).toBeInTheDocument();
    expect(screen.queryByText("Ink shore")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Art style"), { target: { value: "ink" } });
    expect(screen.getByText("Ink shore")).toBeInTheDocument();
    expect(screen.queryByText("The glass shore")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Art style"), { target: { value: "celestial" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Generate illustrations" })));
    expect(codexApi.generateIllustrations).toHaveBeenCalledWith(1, 1, { count: 1, style: "celestial", force: false });
  });

  it("lets readers without generation access browse every available style", async () => {
    codexApi.illustrations.mockResolvedValue({ ...empty, can_generate: false, items: [{ ...art, style: "celestial" }] });
    render(wrap());
    await open();
    expect(screen.queryByText("The glass shore")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Art style"), { target: { value: "celestial" } });
    expect(screen.getByText("The glass shore")).toBeInTheDocument();
    expect(codexApi.generateIllustrations).not.toHaveBeenCalled();
  });

  it("continues checking an active job after a temporary polling failure", async () => {
    vi.useFakeTimers();
    codexApi.illustrations.mockResolvedValueOnce({ ...empty, active_job: { id: "job-1", status: "running" } }).mockRejectedValueOnce(new Error("Connection lost")).mockResolvedValue({ ...empty, active_job: { id: "job-1", status: "failed", error: "Image generation reached its limit." } });
    render(wrap());
    await open();
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(screen.getByRole("alert")).toHaveTextContent("Connection lost");
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(screen.getByRole("alert")).toHaveTextContent("Image generation reached its limit.");
    expect(screen.getByRole("button", { name: "Generate illustrations" })).toBeEnabled();
    await act(async () => vi.advanceTimersByTimeAsync(10000));
    expect(codexApi.illustrations).toHaveBeenCalledTimes(3);
    expect(codexApi.generateIllustrations).not.toHaveBeenCalled();
  });
});
