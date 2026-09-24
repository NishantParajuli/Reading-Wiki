import React, { useState } from "react";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test } from "vitest";
import { useFocusTrap } from "./hooks.js";

afterEach(() => { cleanup(); document.body.style.overflow = ""; });
function Dialog({ children }) { const ref = useFocusTrap(true); return <div ref={ref} role="dialog">{children}</div>; }
function Nested() {
  const [open, setOpen] = useState(false);
  return <Dialog><button onClick={() => setOpen(true)}>Open child</button><button>Parent last</button>{open && <Dialog><input disabled aria-label="Disabled" /><button onClick={() => setOpen(false)}>Close child</button></Dialog>}</Dialog>;
}
test("nested dialogs keep scrolling locked, trap focus and restore the original overflow", async () => {
  document.body.style.overflow = "clip";
  const user = userEvent.setup();
  const { unmount } = render(<Nested />);
  await user.click(screen.getByRole("button", { name: "Open child" }));
  expect(screen.getByRole("button", { name: "Close child" })).toHaveFocus();
  await user.tab();
  expect(screen.getByRole("button", { name: "Close child" })).toHaveFocus();
  await user.click(screen.getByRole("button", { name: "Close child" }));
  expect(document.body.style.overflow).toBe("hidden");
  expect(screen.getByRole("button", { name: "Open child" })).toHaveFocus();
  unmount();
  expect(document.body.style.overflow).toBe("clip");
});
test("a dialog without enabled controls contains keyboard focus", async () => {
  const user = userEvent.setup();
  render(<><button>Behind dialog</button><Dialog><button disabled>Unavailable</button></Dialog></>);
  expect(screen.getByRole("dialog")).toHaveFocus();
  await user.tab();
  expect(screen.getByRole("dialog")).toHaveFocus();
});
