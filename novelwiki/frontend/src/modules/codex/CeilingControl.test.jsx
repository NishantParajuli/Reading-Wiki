import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const novelContext = vi.hoisted(() => ({
  ceiling: 24,
  setCeiling: vi.fn(),
  stats: { ceiling_title: "The Visitor", entities_revealed: 17 },
  codexMeta: { min: 1, max: 1432.003, bookMax: 1432.003 },
}));

vi.mock("../../layouts/NovelLayout.jsx", () => ({
  useNovel: () => novelContext,
}));

import { CeilingControl } from "./CeilingControl.jsx";

describe("CeilingControl", () => {
  beforeEach(() => {
    novelContext.ceiling = 24;
    novelContext.setCeiling.mockReset();
  });

  async function openControl() {
    const user = userEvent.setup();
    render(<CeilingControl />);
    await user.click(screen.getByRole("button", { name: /bounded to/i }));
    return user;
  }

  it("sets an exact chapter without dragging the range slider", async () => {
    const user = await openControl();
    const input = screen.getByLabelText("Go directly to chapter");

    await user.clear(input);
    await user.type(input, "1200.5");
    await user.click(screen.getByRole("button", { name: "Set" }));

    expect(novelContext.setCeiling).toHaveBeenCalledWith(1200.5);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps out-of-range chapters from changing the ceiling", async () => {
    const user = await openControl();
    const input = screen.getByLabelText("Go directly to chapter");

    await user.clear(input);
    await user.type(input, "2000");
    await user.click(screen.getByRole("button", { name: "Set" }));

    expect(novelContext.setCeiling).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a chapter from 1 to 1432.003.");
  });
});
