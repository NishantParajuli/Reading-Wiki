import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Ask } from "./Ask.jsx";
import { CodexBrowser } from "./Browser.jsx";
import { codexApi } from "./api.js";
import { experienceApi } from "../experience/api.js";

let novelContext;
vi.mock("../../layouts/NovelLayout.jsx", () => ({ useNovel: () => novelContext }));
vi.mock("./CeilingControl.jsx", () => ({ CeilingControl: () => null }));
const wrap = component => <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>{component}</MemoryRouter>;

beforeEach(() => {
  novelContext = { novelId: 1, novel: { title: "A quiet sea" }, ceiling: 9, stats: {}, codexMeta: { max: 20 } };
});

describe("spoiler boundary changes", () => {
  it("discards an answer that arrives after the reader lowers their chapter boundary", async () => {
    let finish;
    vi.spyOn(codexApi, "ask").mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const { rerender } = render(wrap(<Ask />));
    fireEvent.change(screen.getByRole("textbox", { name: "Your question" }), { target: { value: "Who is the captain?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(codexApi.ask).toHaveBeenCalledWith(1, "Who is the captain?", 9));
    novelContext = { ...novelContext, ceiling: 2 };
    rerender(wrap(<Ask />));
    await act(async () => finish({ answer: "The captain is secretly the king.", citations: [] }));
    expect(screen.queryByText(/secretly the king/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recap the story so far" })).toBeInTheDocument();
  });

  it("clears an existing recap immediately when the boundary changes", async () => {
    vi.spyOn(experienceApi, "recap").mockResolvedValue({ answer: "The island sinks in chapter nine.", citations: [] });
    const { rerender } = render(wrap(<Ask />));
    fireEvent.click(screen.getByRole("button", { name: "Recap the story so far" }));
    await screen.findByText("The island sinks in chapter nine.");
    novelContext = { ...novelContext, ceiling: 2 };
    rerender(wrap(<Ask />));
    expect(screen.queryByText("The island sinks in chapter nine.")).not.toBeInTheDocument();
  });

  it("hides codex entries before the debounced lower-boundary request completes", async () => {
    vi.spyOn(codexApi, "listEntities").mockResolvedValue([{ id: 3, name: "Hidden king", type: "character", firstSeen: 9 }]);
    const { rerender } = render(wrap(<CodexBrowser />));
    await screen.findByText("Hidden king");
    novelContext = { ...novelContext, ceiling: 2 };
    rerender(wrap(<CodexBrowser />));
    expect(screen.queryByText("Hidden king")).not.toBeInTheDocument();
    expect(screen.getByText("Opening the codex…")).toBeInTheDocument();
  });

  it("distinguishes a failed codex request from an empty result", async () => {
    vi.spyOn(codexApi, "listEntities").mockRejectedValue(new Error("Connection lost"));
    render(wrap(<CodexBrowser />));
    await screen.findByText("The codex couldn't load");
    expect(screen.getByText("Connection lost")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.queryByText("No matches")).not.toBeInTheDocument();
  });
});
