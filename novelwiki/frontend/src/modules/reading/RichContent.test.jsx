import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RichContent } from "./ReaderParts.jsx";

vi.mock("../codex/index.js", () => ({ Illustration: ({ item }) => <figure data-scene={item.id}>{item.title}</figure> }));

const HTML = '<p>The archive kept its maps in drawers.</p><figure><img src="/plate.png" alt="A drowned staircase"></figure>';

describe("rich chapter pictures", () => {
  it("open in a labelled modal that closes on Escape and returns focus to the picture", () => {
    render(<RichContent html={HTML} />);
    const picture = screen.getByRole("button", { name: "Enlarge image: A drowned staircase" });
    picture.focus();
    fireEvent.keyDown(picture, { key: "Enter" });

    const dialog = screen.getByRole("dialog", { name: "Image: A drowned staircase" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("button", { name: "Close image" })).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(picture).toHaveFocus();
  });

  it("closes from its close button without the tap reaching the page", () => {
    const onPageClick = vi.fn();
    render(<div onClick={onPageClick}><RichContent html={HTML} /></div>);
    fireEvent.click(screen.getByRole("button", { name: "Enlarge image: A drowned staircase" }));
    fireEvent.click(screen.getByRole("button", { name: "Close image" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onPageClick).not.toHaveBeenCalled();
  });
});
