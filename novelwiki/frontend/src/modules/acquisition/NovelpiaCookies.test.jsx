import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { acquisitionApi } from "./api.js";
import { NovelpiaCookies } from "./NovelpiaCookies.jsx";

const empty = { configured: false, usable: false, cookies: [], updated_at: null };
const saved = {
  configured: true, usable: true, updated_at: "2026-09-27T10:00:00Z",
  cookies: [{ name: "TKEY", domain: ".novelpia.com", expires_at: "2027-09-27T10:00:00Z" }],
};
const exported = [{ name: "TKEY", domain: ".novelpia.com", value: "synthetic-session-secret" }];

beforeEach(() => {
  vi.spyOn(acquisitionApi, "novelpiaCookies").mockResolvedValue(empty);
  vi.spyOn(acquisitionApi, "updateNovelpiaCookies").mockResolvedValue(saved);
  vi.spyOn(acquisitionApi, "deleteNovelpiaCookies").mockResolvedValue(empty);
});

describe("Novelpia source account settings", () => {
  it("saves an exported array, clears the input, and displays metadata without secrets", async () => {
    await act(async () => render(<NovelpiaCookies />));
    fireEvent.change(screen.getByLabelText("Cookie export"), { target: { value: JSON.stringify(exported) } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save cookies" })));
    expect(acquisitionApi.updateNovelpiaCookies).toHaveBeenCalledWith(exported);
    expect(screen.getByLabelText("Replace cookies")).toHaveValue("");
    expect(screen.getByRole("status")).toHaveTextContent("Cookies saved");
    expect(document.body).not.toHaveTextContent("synthetic-session-secret");
    expect(screen.queryByText("Connected")).not.toBeInTheDocument();
  });

  it.each(["invalid synthetic-session-secret", '{"value":"synthetic-session-secret"}', "[]"])(
    "rejects malformed or non-array exports without reflecting their values: %s", async value => {
      await act(async () => render(<NovelpiaCookies />));
      fireEvent.change(screen.getByLabelText("Cookie export"), { target: { value } });
      await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save cookies" })));
      expect(acquisitionApi.updateNovelpiaCookies).not.toHaveBeenCalled();
      expect(screen.getByRole("alert")).toHaveTextContent("full JSON array");
      expect(screen.getByRole("alert")).not.toHaveTextContent("synthetic-session-secret");
    },
  );

  it("preserves the export when saving fails so it can be corrected", async () => {
    acquisitionApi.updateNovelpiaCookies.mockRejectedValue(new Error("Export is missing a Novelpia login cookie."));
    await act(async () => render(<NovelpiaCookies />));
    fireEvent.change(screen.getByLabelText("Cookie export"), { target: { value: JSON.stringify(exported) } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save cookies" })));
    expect(screen.getByRole("alert")).toHaveTextContent("missing a Novelpia login cookie");
    expect(screen.getByLabelText("Cookie export")).toHaveValue(JSON.stringify(exported));
    expect(screen.getByRole("button", { name: "Save cookies" })).toBeEnabled();
  });

  it("removes saved credentials and clears any pending replacement", async () => {
    acquisitionApi.novelpiaCookies.mockResolvedValue(saved);
    await act(async () => render(<NovelpiaCookies />));
    fireEvent.change(screen.getByLabelText("Replace cookies"), { target: { value: JSON.stringify(exported) } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Remove saved cookies" })));
    expect(acquisitionApi.deleteNovelpiaCookies).toHaveBeenCalledOnce();
    expect(screen.getByRole("status")).toHaveTextContent("removed");
    expect(screen.getByLabelText("Cookie export")).toHaveValue("");
    expect(screen.queryByRole("button", { name: "Remove saved cookies" })).not.toBeInTheDocument();
  });

  it("offers retry on a failed status request instead of claiming no saved cookies", async () => {
    acquisitionApi.novelpiaCookies.mockRejectedValueOnce(new Error("offline"));
    await act(async () => render(<NovelpiaCookies />));
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load");
    expect(screen.queryByText("No cookies saved")).not.toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Try again" })));
    expect(screen.getByLabelText("Cookie export")).toBeVisible();
  });

  it("shows expired credentials without claiming the login is connected", async () => {
    acquisitionApi.novelpiaCookies.mockResolvedValue({ ...saved, usable: false });
    await act(async () => render(<NovelpiaCookies />));
    expect(screen.getByText("Update needed")).toBeVisible();
    expect(screen.getByText(/Sign in to Novelpia and replace/)).toBeVisible();
  });

  it("can replace unreadable cookies after the server encryption key changes", async () => {
    acquisitionApi.novelpiaCookies.mockRejectedValue(Object.assign(new Error("unreadable"), { status: 422 }));
    await act(async () => render(<NovelpiaCookies />));
    expect(screen.getByRole("alert")).toHaveTextContent("saved cookies cannot be opened");
    fireEvent.change(screen.getByLabelText("Cookie export"), { target: { value: JSON.stringify(exported) } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save cookies" })));
    expect(acquisitionApi.updateNovelpiaCookies).toHaveBeenCalledWith(exported);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Replace cookies")).toHaveValue("");
    expect(screen.getByRole("status")).toHaveTextContent("Cookies saved");
  });

  it("can remove unreadable cookies without loading or decrypting their values", async () => {
    acquisitionApi.novelpiaCookies.mockRejectedValue(Object.assign(new Error("unreadable"), { status: 422 }));
    await act(async () => render(<NovelpiaCookies />));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Remove saved cookies" })));
    expect(acquisitionApi.deleteNovelpiaCookies).toHaveBeenCalledOnce();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("No cookies saved")).toBeVisible();
  });

  it("disables overlapping changes while a save is pending", async () => {
    let finish;
    acquisitionApi.novelpiaCookies.mockResolvedValue(saved);
    acquisitionApi.updateNovelpiaCookies.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    await act(async () => render(<NovelpiaCookies />));
    fireEvent.change(screen.getByLabelText("Replace cookies"), { target: { value: JSON.stringify(exported) } });
    fireEvent.click(screen.getByRole("button", { name: "Replace cookies" }));
    expect(screen.queryByRole("button", { name: "Removing…" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove saved cookies" })).toBeDisabled();
    expect(screen.getByLabelText("Replace cookies")).toBeDisabled();
    await act(async () => finish(saved));
    await waitFor(() => expect(screen.getByLabelText("Replace cookies")).toBeEnabled());
  });
});
