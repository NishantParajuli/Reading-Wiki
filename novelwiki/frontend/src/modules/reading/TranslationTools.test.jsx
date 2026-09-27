import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TranslationTools } from "./TranslationTools.jsx";
import { readingApi } from "./api.js";

const chapter = { number: 3, title: "The glass sea", content: "First paragraph.\n\nSecond paragraph.", can_edit_base: true };
function open(overrides = {}) {
  const callbacks = { onClose: vi.fn(), onChanged: vi.fn() };
  render(<TranslationTools novelId={12} ch={{ ...chapter, ...overrides }} {...callbacks} />);
  return callbacks;
}
const change = text => fireEvent.change(screen.getByRole("textbox", { name: "Chapter translation" }), { target: { value: text } });

beforeEach(() => {
  for (const key of ["editBaseContent", "saveOverlay", "resolveOverlay", "selfTranslate", "deleteOverlay", "contribute"]) {
    vi.spyOn(readingApi, key).mockResolvedValue({ status: "success" });
  }
});

describe("translation workbench", () => {
  it("shows the chapter, sharing scope and a live safe-text reading preview", () => {
    open();
    expect(screen.getByRole("dialog", { name: "Edit chapter translation" })).toBeInTheDocument();
    expect(screen.getByText("The glass sea")).toBeInTheDocument();
    expect(screen.getByText(/Saving updates the text for every reader/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save for everyone" })).toBeDisabled();
    change("New paragraph.\n\n<script>alert('text')</script>");
    const preview = screen.getByRole("region", { name: "Reading preview" });
    expect(within(preview).getByText("New paragraph.")).toBeInTheDocument();
    expect(within(preview).getByText("<script>alert('text')</script>")).toBeInTheDocument();
    expect(preview.querySelector("script")).toBeNull();
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("saves shared text through the existing shared chapter endpoint", async () => {
    const { onChanged } = open();
    change("A better shared translation.");
    fireEvent.click(screen.getByRole("button", { name: "Save for everyone" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
    expect(readingApi.editBaseContent).toHaveBeenCalledWith(12, 3, "A better shared translation.");
    expect(readingApi.saveOverlay).not.toHaveBeenCalled();
  });

  it("saves personal edits with the keyboard shortcut", async () => {
    const { onChanged } = open({ can_edit_base: false });
    change("My personal wording.");
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "s", ctrlKey: true });
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
    expect(readingApi.saveOverlay).toHaveBeenCalledWith(12, 3, "My personal wording.");
  });

  it("guards Escape before the reader's window listener can discard the draft", async () => {
    const parentEscape = vi.fn();
    window.addEventListener("keydown", parentEscape);
    const { onClose } = open();
    change("Unsaved wording.");
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Escape" });
    expect(screen.getByRole("alertdialog", { name: "Discard your unsaved changes?" })).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(parentEscape).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(screen.getByRole("textbox")).toHaveValue("Unsaved wording.");
    fireEvent.click(screen.getByRole("button", { name: "Close translation editor" }));
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(onClose).toHaveBeenCalledOnce();
    window.removeEventListener("keydown", parentEscape);
  });

  it("keeps failed saves and their draft visible for retry", async () => {
    readingApi.editBaseContent.mockRejectedValue(new Error("Connection interrupted"));
    const { onChanged } = open();
    change("Keep these changes.");
    fireEvent.click(screen.getByRole("button", { name: "Save for everyone" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Connection interrupted");
    expect(screen.getByRole("textbox")).toHaveValue("Keep these changes.");
    expect(screen.getByRole("button", { name: "Save for everyone" })).toBeEnabled();
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("blocks closing and duplicate operations while a save is pending", async () => {
    let resolve;
    readingApi.editBaseContent.mockImplementation(() => new Promise(done => { resolve = done; }));
    const { onClose, onChanged } = open();
    change("Saving safely.");
    fireEvent.click(screen.getByRole("button", { name: "Save for everyone" }));
    expect(screen.getByRole("status")).toHaveTextContent("Saving the shared chapter…");
    expect(screen.getByRole("button", { name: "Close translation editor" })).toBeDisabled();
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.keyDown(document, { key: "s", metaKey: true });
    expect(onClose).not.toHaveBeenCalled();
    expect(readingApi.editBaseContent).toHaveBeenCalledOnce();
    await act(async () => resolve({}));
    expect(onChanged).toHaveBeenCalledOnce();
  });

  it("retains merged-text conflict resolution and comparison", async () => {
    const { onChanged } = open({ can_edit_base: false, overlay: true, overlay_conflict: true, base_content: "The latest shared version." });
    fireEvent.click(screen.getByRole("button", { name: "Compare versions" }));
    expect(screen.getByRole("region", { name: "Translation comparison" })).toBeInTheDocument();
    change("A considered merge.");
    fireEvent.click(screen.getByRole("button", { name: "Save merged version" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
    expect(readingApi.resolveOverlay).toHaveBeenCalledWith(12, 3, "merge", "A considered merge.");
  });

  it.each([["Keep saved version", "mine"], ["Use latest shared version", "base"]])("preserves the %s conflict action", async (label, choice) => {
    const { onChanged } = open({ can_edit_base: false, overlay: true, overlay_conflict: true });
    fireEvent.click(screen.getByRole("button", { name: label }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
    expect(readingApi.resolveOverlay).toHaveBeenCalledWith(12, 3, choice);
  });

  it("protects unsaved edits before generating a new personal translation", async () => {
    const { onChanged } = open({ has_original: true });
    change("An unsaved translation.");
    fireEvent.click(screen.getByRole("button", { name: "Re-translate for me" }));
    expect(readingApi.selfTranslate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Replace translation" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
    expect(readingApi.selfTranslate).toHaveBeenCalledWith(12, 3);
  });

  it("offers only saved personal text to the owner", async () => {
    open({ can_edit_base: false, overlay: true });
    fireEvent.click(screen.getByRole("button", { name: "Offer to owner" }));
    expect(await screen.findByRole("status")).toHaveTextContent(/sent to the owner/);
    expect(readingApi.contribute).toHaveBeenCalledWith(12, 3);
    change("Not saved yet.");
    expect(screen.getByRole("button", { name: "Offer to owner" })).toBeDisabled();
  });

  it("confirms deletion of a personal overlay before restoring shared text", async () => {
    const { onChanged } = open({ can_edit_base: false, overlay: true });
    fireEvent.click(screen.getByRole("button", { name: "Revert to shared version" }));
    expect(readingApi.deleteOverlay).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Replace translation" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
    expect(readingApi.deleteOverlay).toHaveBeenCalledWith(12, 3);
  });

  it("restores focus and scroll state after a clean close", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [show, setShow] = React.useState(false);
      return <><button onClick={() => setShow(true)}>Open editor</button>{show && <TranslationTools novelId={12} ch={chapter} onClose={() => setShow(false)} onChanged={() => setShow(false)} />}</>;
    }
    document.body.style.overflow = "auto";
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Open editor" });
    await user.click(trigger);
    expect(document.body.style.overflow).toBe("hidden");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(trigger).toHaveFocus();
    expect(document.body.style.overflow).toBe("auto");
    document.body.style.overflow = "";
  });
});
