import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChapterIllustrations, Illustration } from "./ChapterIllustrations.jsx";
import { codexApi } from "./api.js";

const empty = { items: [], can_generate: true, active_job: null };
const art = { id: "scene-1", kind: "scene", title: "The glass shore", caption: "Mira watches the tide.", style: "luminous", image_url: "/api/novels/1/illustrations/scene-1/image" };
const wrap = (chapter = 1) => <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><ChapterIllustrations novelId={1} chapter={chapter}>{scenes => <article>{scenes.map(item => <Illustration key={item.id} item={item} inline />)}</article>}</ChapterIllustrations></MemoryRouter>;
const open = async () => { await act(async () => fireEvent.click(screen.getByRole("button", { name: /Illustrate this chapter/ }))); };

beforeEach(() => {
  vi.spyOn(codexApi, "illustrations").mockResolvedValue(empty);
  vi.spyOn(codexApi, "generateIllustrations").mockResolvedValue({ job_id: "job-1" });
});
afterEach(() => vi.useRealTimers());

describe("chapter illustrations", () => {
  it("loads existing art automatically and never starts generation without an explicit action", async () => {
    render(wrap());
    expect(codexApi.illustrations).toHaveBeenCalledWith(1, 1);
    await open();
    expect(codexApi.illustrations).toHaveBeenCalledWith(1, 1);
    expect(screen.queryByLabelText("Scenes")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Art style")).toHaveValue("luminous");
    expect(codexApi.generateIllustrations).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Art style"), { target: { value: "painterly" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Generate illustrations" })));
    expect(codexApi.generateIllustrations).toHaveBeenCalledWith(1, 1, { style: "painterly", force: false });
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
    expect(codexApi.generateIllustrations).toHaveBeenCalledWith(1, 1, { style: "luminous", force: true });
    expect(screen.getByRole("alert")).toHaveTextContent("Codex is unavailable");
    expect(screen.getByText("The glass shore")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate again" })).toBeEnabled();
  });

  it("shows only the chosen style and regenerates the selected style", async () => {
    codexApi.illustrations.mockResolvedValue({ ...empty, items: [art, { ...art, id: "painterly-1", title: "Painted shore", style: "painterly" }] });
    render(wrap());
    await open();
    expect(screen.getByText("The glass shore")).toBeInTheDocument();
    expect(screen.queryByText("Painted shore")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Art style"), { target: { value: "painterly" } });
    expect(screen.getByText("Painted shore")).toBeInTheDocument();
    expect(screen.queryByText("The glass shore")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Art style")).toHaveAccessibleDescription("Semi-realistic characters, textured brushwork, and cinematic lighting.");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Generate again" })));
    expect(codexApi.generateIllustrations).toHaveBeenCalledWith(1, 1, { style: "painterly", force: true });
  });

  it.each([true, false])("keeps Luminous anime selected and legacy art separate when can_generate=%s", async canGenerate => {
    codexApi.illustrations.mockResolvedValue({ ...empty, can_generate: canGenerate, items: [{ ...art, style: "celestial" }, { ...art, id: "ink-1", style: "ink", title: "Old ink art" }] });
    render(wrap());
    await open();
    expect(screen.getByLabelText("Art style")).toHaveValue("luminous");
    expect(screen.getAllByRole("option").map(option => option.textContent)).toEqual(["Luminous anime", "Painterly"]);
    expect(screen.getByLabelText("Art style")).toHaveAccessibleDescription("Expressive anime characters, clean linework, soft cel shading, and luminous light.");
    expect(screen.getByText("Earlier illustrations")).toBeInTheDocument();
    expect(screen.getByText("The glass shore").closest("details")).not.toHaveAttribute("open");
    expect(document.querySelector("article .chapter-art")).toBeNull();
    expect(codexApi.generateIllustrations).not.toHaveBeenCalled();
  });

  it("defaults to anime when only painterly art exists and does not force new anime scenes", async () => {
    codexApi.illustrations.mockResolvedValue({ ...empty, items: [{ ...art, style: "painterly" }] });
    render(wrap());
    await open();
    expect(screen.getByLabelText("Art style")).toHaveValue("luminous");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Generate illustrations" })));
    expect(codexApi.generateIllustrations).toHaveBeenCalledWith(1, 1, { style: "luminous", force: false });
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
