import React, { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Popover } from "./overlay.jsx";

function rect(left, right) {
  return { left, right, top: 0, bottom: 32, width: right - left, height: 32, x: left, y: 0, toJSON() {} };
}

describe("Popover viewport positioning", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  function renderPopover({ anchorLeft, anchorRight, align = "right", viewportWidth = 378 }) {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function () {
      return this.classList.contains("usermenu") ? rect(anchorLeft, anchorRight) : rect(0, 280);
    });
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(function () {
      return this.classList.contains("popover") ? 280 : anchorRight - anchorLeft;
    });
    vi.spyOn(document.documentElement, "clientWidth", "get").mockReturnValue(viewportWidth);

    render(
      <Popover open onClose={() => {}} align={align} trigger={<button>Voice</button>}>
        Narrator choices
      </Popover>,
    );
    return screen.getByText("Narrator choices");
  }

  it("shifts a right-aligned narrator menu inside the left viewport edge", () => {
    const panel = renderPopover({ anchorLeft: 28, anchorRight: 134 });

    expect(panel.style.left).toBe("-16px");
    expect(panel.style.right).toBe("auto");
  });

  it("shifts a left-aligned menu inside the right viewport edge", () => {
    const panel = renderPopover({ anchorLeft: 260, anchorRight: 330, align: "left", viewportWidth: 320 });

    expect(panel.style.left).toBe("-232px");
    expect(panel.style.right).toBe("auto");
  });
});

describe("Popover focus", () => {
  function Harness() {
    const [open, setOpen] = useState(false);
    return (
      <Popover open={open} onClose={() => setOpen(false)}
               trigger={<button type="button" aria-expanded={open} onClick={() => setOpen(o => !o)}>Sort</button>}>
        <button type="button" onClick={() => setOpen(false)}>Newest</button>
      </Popover>
    );
  }

  it("hands focus back to its trigger when Escape closes it from inside", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Sort" }));
    screen.getByRole("button", { name: "Newest" }).focus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("button", { name: "Newest" })).not.toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Sort" }));
  });

  it("hands focus back to its trigger after choosing an item", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Sort" }));
    const item = screen.getByRole("button", { name: "Newest" });
    item.focus();
    fireEvent.click(item);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Sort" }));
  });
});
