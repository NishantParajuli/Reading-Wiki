import React, { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Button, Tabs } from "./ui.jsx";

function TabsHarness() {
  const [value, setValue] = useState("a");
  return (
    <Tabs label="Lists" idBase="t" value={value} onChange={setValue}
          tabs={[{ id: "a", label: "Alpha" }, { id: "b", label: "Beta" }, { id: "c", label: "Gamma" }]} />
  );
}

describe("Tabs", () => {
  it("keeps one Tab stop and moves the selection with arrows, Home and End", () => {
    render(<TabsHarness />);
    expect(screen.getByRole("tablist", { name: "Lists" })).toBeInTheDocument();
    const alpha = screen.getByRole("tab", { name: "Alpha" });
    expect(alpha).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tab", { name: "Beta" })).toHaveAttribute("tabindex", "-1");
    expect(alpha).toHaveAttribute("id", "t-tab-a");
    expect(alpha).toHaveAttribute("aria-controls", "t-panel");

    alpha.focus();
    fireEvent.keyDown(alpha, { key: "ArrowRight" });
    const beta = screen.getByRole("tab", { name: "Beta" });
    expect(beta).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(beta);

    fireEvent.keyDown(beta, { key: "End" });
    expect(screen.getByRole("tab", { name: "Gamma" })).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(document.activeElement, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Alpha" })).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(document.activeElement, { key: "ArrowLeft" });
    expect(screen.getByRole("tab", { name: "Gamma" })).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(document.activeElement, { key: "Home" });
    expect(document.activeElement).toBe(screen.getByRole("tab", { name: "Alpha" }));
  });
});

describe("Button", () => {
  it("stays focusable while loading and ignores presses until it's done", () => {
    const onClick = vi.fn();
    const { rerender } = render(<Button onClick={onClick}>Save</Button>);
    const button = screen.getByRole("button", { name: "Save" });
    button.focus();

    rerender(<Button onClick={onClick} loading>Save</Button>);
    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(document.activeElement).toBe(button);
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();

    rerender(<Button onClick={onClick}>Save</Button>);
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("does not submit its form while loading", () => {
    const onSubmit = vi.fn(event => event.preventDefault());
    render(<form onSubmit={onSubmit}><Button type="submit" loading>Send</Button></form>);
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("keeps a truly disabled button disabled", () => {
    render(<Button disabled loading>Wait</Button>);
    expect(screen.getByRole("button", { name: "Wait" })).toBeDisabled();
  });
});
