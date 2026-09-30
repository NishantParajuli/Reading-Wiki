import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CodexBrowser } from "./Browser.jsx";
import { codexApi } from "./api.js";

let novelContext;
vi.mock("../../layouts/NovelLayout.jsx", () => ({ useNovel: () => novelContext }));
vi.mock("./CeilingControl.jsx", () => ({ CeilingControl: () => null }));
const wrap = component => <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>{component}</MemoryRouter>;

const people = [
  { id: 1, name: "Mira Vale", type: "character", firstSeen: 1 },
  { id: 5, name: "The Order of Low Water", type: "faction", firstSeen: 6 },
];
const guild = { id: 11, name: "The Cartographers' Guild", type: "organization", firstSeen: 15 };

beforeEach(() => {
  novelContext = { novelId: 1, novel: { title: "A quiet sea" }, ceiling: 20, stats: {}, codexMeta: { max: 20 } };
});

describe("codex browser filters", () => {
  it("offers Organizations only when the book has some, and filters by it", async () => {
    const list = vi.spyOn(codexApi, "listEntities").mockImplementation(async (_novel, _ceiling, { type }) => (
      type ? [...people, guild].filter(e => e.type === type) : [...people, guild]
    ));
    render(wrap(<CodexBrowser />));
    await screen.findByText("The Cartographers' Guild");
    const orgs = screen.getByRole("button", { name: "Organizations" });
    expect(orgs).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(orgs);
    await waitFor(() => expect(list).toHaveBeenLastCalledWith(1, 20, { type: "organization", q: null }));
    await waitFor(() => expect(screen.queryByText("Mira Vale")).not.toBeInTheDocument());
    expect(screen.getByText("The Cartographers' Guild")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Organizations" })).toHaveAttribute("aria-pressed", "true");
  });

  it("leaves Organizations out when there are none at this boundary", async () => {
    vi.spyOn(codexApi, "listEntities").mockResolvedValue(people);
    render(wrap(<CodexBrowser />));
    await screen.findByText("Mira Vale");
    expect(screen.getByRole("button", { name: "Factions" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Organizations" })).not.toBeInTheDocument();
  });
});
