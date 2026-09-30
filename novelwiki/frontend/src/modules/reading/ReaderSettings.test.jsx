import React, { useRef, useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OverlayHostProvider } from "../../components/overlay.jsx";
import { loadReaderPrefs } from "./ReaderParts.jsx";
import { ReaderSettings } from "./ReaderSettings.jsx";

// Like the reader: the panel opens from its Aa button once the page is mounted.
function Harness({ onClose = () => {}, initial = {} }) {
  const hostRef = useRef(null);
  const aaRef = useRef(null);
  const [prefs, setPrefs] = useState(() => ({ ...loadReaderPrefs(null), ...initial }));
  const [open, setOpen] = useState(false);
  return (
    <OverlayHostProvider hostRef={hostRef}>
      <div ref={hostRef} className="reader" data-testid="host">
        <button ref={aaRef} type="button" aria-label="Reading settings" onClick={() => setOpen(o => !o)}>Aa</button>
        <output data-testid="tone">{prefs.tone}</output>
        <output data-testid="font">{prefs.font}</output>
        {open && <ReaderSettings prefs={prefs} setPrefs={setPrefs} anchorRef={aaRef}
                                 onClose={() => { onClose(); setOpen(false); }} />}
      </div>
    </OverlayHostProvider>
  );
}

function openSettings(ui) {
  const view = render(ui);
  fireEvent.click(screen.getByRole("button", { name: "Reading settings" }));
  return view;
}

describe("reading settings", () => {
  it("renders at the reader root and moves focus to its title", () => {
    openSettings(<Harness />);
    const panel = screen.getByRole("dialog", { name: "Reading settings" });
    expect(panel.parentElement).toBe(screen.getByTestId("host"));
    expect(screen.getByRole("heading", { name: "Make yourself comfortable" })).toHaveFocus();
  });

  it("gives each radio group one Tab stop and lets arrows move and choose", () => {
    openSettings(<Harness initial={{ tone: "paper" }} />);
    const tones = screen.getByRole("radiogroup", { name: "Reading tone" });
    const radios = Array.from(tones.querySelectorAll("[role='radio']"));
    expect(radios.map(r => r.tabIndex)).toEqual([-1, 0, -1, -1, -1]);
    expect(radios[1]).toHaveAttribute("aria-checked", "true");

    radios[1].focus();
    fireEvent.keyDown(radios[1], { key: "ArrowRight" });
    expect(screen.getByTestId("tone")).toHaveTextContent("sepia");
    expect(radios[2]).toHaveFocus();
    expect(radios.map(r => r.tabIndex)).toEqual([-1, -1, 0, -1, -1]);

    fireEvent.keyDown(radios[2], { key: "End" });
    expect(screen.getByTestId("tone")).toHaveTextContent("night");
    fireEvent.keyDown(radios[4], { key: "ArrowRight" });
    expect(screen.getByTestId("tone")).toHaveTextContent("default");
    expect(radios[0]).toHaveFocus();

    const fonts = Array.from(screen.getByRole("radiogroup", { name: "Font" }).querySelectorAll("[role='radio']"));
    fonts[0].focus();
    fireEvent.keyDown(fonts[0], { key: "ArrowLeft" });
    expect(screen.getByTestId("font")).toHaveTextContent("legible");
    expect(fonts[3]).toHaveFocus();
  });

  it("hands focus back to the Aa button on Escape and on close", () => {
    const onClose = vi.fn();
    const { unmount } = openSettings(<Harness onClose={onClose} />);
    fireEvent.keyDown(document.activeElement, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reading settings" })).toHaveFocus();
    unmount();

    openSettings(<Harness onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Close reading settings" }));
    expect(onClose).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "Reading settings" })).toHaveFocus();
  });

  it("keeps clicks inside from reaching the page's tap-to-hide", () => {
    const onPageClick = vi.fn();
    openSettings(<div onClick={onPageClick}><Harness /></div>);
    onPageClick.mockClear();
    fireEvent.click(screen.getByRole("slider", { name: "Font size" }));
    expect(onPageClick).not.toHaveBeenCalled();
  });
});
