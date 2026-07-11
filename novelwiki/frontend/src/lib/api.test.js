import { beforeEach, describe, expect, it, vi } from "vitest";

import { API, setUnauthorizedHandler } from "./api.js";

function response(body, { status = 200, statusText = "OK" } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    json: vi.fn().mockResolvedValue(body),
  };
}

describe("HTTP compatibility transport", () => {
  beforeEach(() => {
    document.cookie = "tg_csrf=reader-token; path=/";
    global.fetch = vi.fn().mockResolvedValue(response({ status: "success" }));
    setUnauthorizedHandler(null);
  });

  it("preserves credentials and CSRF/request headers for progress mutations", async () => {
    await API.setProgress(12, { last_chapter: 4, scroll_pct: 0.75 });

    expect(fetch).toHaveBeenCalledWith("/api/novels/12/progress", {
      method: "PUT",
      credentials: "include",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-Tideglass-CSRF": "reader-token",
        "X-Tideglass-Request": "1",
      },
      body: JSON.stringify({ last_chapter: 4, scroll_pct: 0.75 }),
    });
  });

  it("keeps ordinary reads free of mutation headers", async () => {
    await API.chapter(7, 2.5);
    const [, options] = fetch.mock.calls[0];
    expect(options.credentials).toBe("include");
    expect(options.headers).toEqual({ Accept: "application/json" });
  });

  it("re-gates on non-auth 401 but not login failures", async () => {
    const unauthorized = vi.fn();
    setUnauthorizedHandler(unauthorized);
    fetch.mockResolvedValue(response({ detail: "Not authenticated." }, { status: 401, statusText: "Unauthorized" }));

    await expect(API.novels()).rejects.toThrow("Not authenticated.");
    expect(unauthorized).toHaveBeenCalledOnce();

    unauthorized.mockClear();
    await expect(API.auth.login("reader", "wrong")).rejects.toThrow("Not authenticated.");
    expect(unauthorized).not.toHaveBeenCalled();
  });

  it("keeps resumable upload offsets and CSRF headers", async () => {
    fetch
      .mockResolvedValueOnce(response({ id: 44 }))
      .mockResolvedValueOnce(response({ offset: 3 }))
      .mockResolvedValueOnce(response({ id: 44, status: "uploaded" }));
    const file = new File(["abc"], "book.epub", { type: "application/epub+zip" });

    await API.uploadChunked(file);

    expect(fetch.mock.calls[1][0]).toBe("/api/import/upload/44/chunk");
    expect(fetch.mock.calls[1][1].headers).toMatchObject({
      "Upload-Offset": "0",
      "Content-Type": "application/octet-stream",
      "X-Tideglass-CSRF": "reader-token",
      "X-Tideglass-Request": "1",
    });
  });
});
