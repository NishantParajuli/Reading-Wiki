import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { acquisitionApi } from "../acquisition/api.js";
import { catalogApi } from "./api.js";
import { AddNovelDialog } from "./AddNovelDialog.jsx";
import { AddSourceForm } from "./AddSourceForm.jsx";
import { EditSourceForm } from "./ManagePanels.jsx";

const adapters = [
  { name: "english", label: "English source", default_language: "en", start_url_hint: "Paste a chapter URL." },
  { name: "korean", label: "Korean source", default_language: "ko", start_url_hint: "Paste a novel catalogue URL." },
  { name: "raw-fucknovelpia", label: "Raw archive source", default_language: "ko", start_url_hint: "Paste a novel URL and enter the ZIP password." },
];

beforeEach(() => {
  vi.spyOn(acquisitionApi, "adapters").mockResolvedValue(adapters);
  vi.spyOn(acquisitionApi, "addSource").mockResolvedValue({ id: 8 });
  vi.spyOn(catalogApi, "createNovel").mockResolvedValue({ id: 4 });
  vi.spyOn(acquisitionApi, "updateSource").mockResolvedValue({ status: "success", renumbered: 0 });
});

const cases = [
  { label: "new novel", Component: AddNovelDialog, submit: "Add to library", api: () => catalogApi.createNovel, setup: () => fireEvent.change(screen.getByLabelText("Title"), { target: { value: "A book" } }) },
  { label: "additional source", Component: AddSourceForm, submit: "Add source", api: () => acquisitionApi.addSource, setup: () => {} },
];

describe.each(cases)("$label form", ({ Component, submit, api, setup }) => {
  function open() {
    render(<Component novelId={4} onCreated={vi.fn()} onAdded={vi.fn()} onClose={vi.fn()} onCancel={vi.fn()} />);
    setup();
    fireEvent.change(screen.getByLabelText("Novel or chapter URL"), { target: { value: "https://example.com/novel/a-book" } });
  }

  it("waits for source metadata and recovers from a failed load", async () => {
    let reject;
    acquisitionApi.adapters.mockImplementationOnce(() => new Promise((resolve, fail) => { reject = fail; }));
    open();
    expect(screen.getByRole("button", { name: submit })).toBeDisabled();
    fireEvent.submit(screen.getByRole("button", { name: submit }).closest("form"));
    expect(api()).not.toHaveBeenCalled();
    await act(async () => { reject(new Error("Sources unavailable")); });
    expect(await screen.findByRole("alert")).toHaveTextContent("Sources unavailable");
    expect(screen.getByRole("button", { name: submit })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByRole("button", { name: submit })).toBeEnabled());
    expect(acquisitionApi.adapters).toHaveBeenCalledTimes(2);
  });

  it("sets language and translation defaults when the website changes, preserving explicit overrides on submit", async () => {
    open();
    await screen.findByRole("option", { name: "Korean source" });
    fireEvent.change(screen.getByLabelText("Website"), { target: { value: "korean" } });
    expect(screen.getByLabelText("Language")).toHaveValue("ko");
    expect(screen.getByLabelText("Raw (needs translation)")).toBeChecked();
    expect(screen.getByLabelText("Novel or chapter URL")).toHaveAccessibleDescription("Paste a novel catalogue URL.");
    fireEvent.change(screen.getByLabelText("Language"), { target: { value: "en" } });
    fireEvent.click(screen.getByLabelText("Raw (needs translation)"));
    fireEvent.click(screen.getByRole("button", { name: submit }));
    await waitFor(() => expect(api()).toHaveBeenCalled());
    const payload = api().mock.calls[0].at(-1);
    expect(payload.source || payload).toMatchObject({ adapter: "korean", language: "en", is_raw: false });
  });

  it("clears raw defaults when returning to an English website", async () => {
    open();
    await screen.findByRole("option", { name: "Korean source" });
    fireEvent.change(screen.getByLabelText("Website"), { target: { value: "korean" } });
    fireEvent.change(screen.getByLabelText("Website"), { target: { value: "english" } });
    expect(screen.getByLabelText("Language")).toHaveValue("en");
    expect(screen.getByLabelText("Raw (needs translation)")).not.toBeChecked();
  });

  it("requires an archive password and does not send it to another adapter", async () => {
    open();
    await screen.findByRole("option", { name: "Raw archive source" });
    fireEvent.change(screen.getByLabelText("Website"), { target: { value: "raw-fucknovelpia" } });
    const password = screen.getByLabelText("ZIP password");
    expect(password).toHaveAttribute("type", "password");
    fireEvent.submit(screen.getByRole("button", { name: submit }).closest("form"));
    expect(api()).not.toHaveBeenCalled();
    fireEvent.change(password, { target: { value: "test-only-passphrase" } });
    fireEvent.change(screen.getByLabelText("Website"), { target: { value: "english" } });
    expect(screen.queryByLabelText("ZIP password")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: submit }));
    await waitFor(() => expect(api()).toHaveBeenCalled());
    const payload = api().mock.calls[0].at(-1);
    expect((payload.source || payload).config).toBeNull();
  });

  it("saves the supplied archive password with the selected raw source", async () => {
    open();
    await screen.findByRole("option", { name: "Raw archive source" });
    fireEvent.change(screen.getByLabelText("Website"), { target: { value: "raw-fucknovelpia" } });
    fireEvent.change(screen.getByLabelText("ZIP password"), { target: { value: "test-only-passphrase" } });
    fireEvent.click(screen.getByRole("button", { name: submit }));
    await waitFor(() => expect(api()).toHaveBeenCalled());
    const payload = api().mock.calls[0].at(-1);
    expect(payload.source || payload).toMatchObject({
      adapter: "raw-fucknovelpia", is_raw: true, config: { archive_password: "test-only-passphrase" },
    });
  });
});

it("rejects invalid continuation numbers and preserves a valid fractional offset", async () => {
  render(<AddSourceForm novelId={4} onAdded={vi.fn()} onCancel={vi.fn()} />);
  await screen.findByRole("option", { name: "Korean source" });
  fireEvent.change(screen.getByLabelText("Novel or chapter URL"), { target: { value: "https://example.com/novel/a-book" } });
  const global = screen.getByLabelText("Continues from global chapter");
  fireEvent.change(global, { target: { value: "125" } });
  const local = screen.getByLabelText("Source-local starting chapter");
  for (const invalid of ["Infinity", "NaN", "2oops"]) {
    fireEvent.change(local, { target: { value: invalid } });
    fireEvent.click(screen.getByRole("button", { name: "Add source" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter valid chapter numbers");
    expect(acquisitionApi.addSource).not.toHaveBeenCalled();
  }
  fireEvent.change(global, { target: { value: "125.5" } });
  fireEvent.change(local, { target: { value: "2" } });
  fireEvent.click(screen.getByRole("button", { name: "Add source" }));
  await waitFor(() => expect(acquisitionApi.addSource).toHaveBeenCalledWith(4, expect.objectContaining({ chapter_offset: 123.5 })));
});

describe("editing a raw archive source", () => {
  const source = { id: 8, adapter: "raw-fucknovelpia", chapter_offset: 0 };

  it("changes the password without reading the old one or renumbering chapters", async () => {
    const onSaved = vi.fn();
    render(<EditSourceForm novelId={4} source={source} onSaved={onSaved} onCancel={vi.fn()} />);
    const password = screen.getByLabelText("New ZIP password");
    expect(password).toHaveValue("");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.change(password, { target: { value: "test-only-replacement" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(acquisitionApi.updateSource).toHaveBeenCalledWith(4, 8, { config: { archive_password: "test-only-replacement" } });
    expect(password).toHaveValue("");
  });

  it("leaves the password unchanged while editing a valid offset", async () => {
    render(<EditSourceForm novelId={4} source={source} onSaved={vi.fn()} onCancel={vi.fn()} />);
    const offset = screen.getByLabelText("Chapter offset (added to this source's own numbers)");
    fireEvent.change(offset, { target: { value: "Infinity" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a valid chapter offset");
    expect(acquisitionApi.updateSource).not.toHaveBeenCalled();
    fireEvent.change(offset, { target: { value: "-1.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(acquisitionApi.updateSource).toHaveBeenCalledWith(4, 8, { chapter_offset: -1.5 }));
  });

  it("keeps a failed password change retryable and shows the server error", async () => {
    acquisitionApi.updateSource.mockRejectedValueOnce(new Error("Source unavailable"));
    const onSaved = vi.fn();
    render(<EditSourceForm novelId={4} source={source} onSaved={onSaved} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("New ZIP password"), { target: { value: "test-only-replacement" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Source unavailable");
    expect(onSaved).not.toHaveBeenCalled();
    expect(screen.getByLabelText("New ZIP password")).toHaveValue("test-only-replacement");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });
});
