import { beforeEach, describe, expect, it } from "vitest";
import { loadReaderPrefs } from "./ReaderParts.jsx";

describe("restored reader preferences", () => {
  beforeEach(() => localStorage.clear());

  it("repairs invalid persisted values before settings render", () => {
    localStorage.setItem("nw-reader", JSON.stringify({
      size: 900, line: "not a number", tone: "obsolete", font: "unknown", autoScroll: "false", autoSpeed: -2,
    }));
    expect(loadReaderPrefs(null)).toMatchObject({
      size: 28, line: 1.7, tone: "default", font: "serif", autoScroll: false, autoSpeed: 1,
    });
  });

  it("normalizes valid synced numeric strings and preserves explicit booleans", () => {
    const prefs = loadReaderPrefs({ prefs: { reader: { line: "1.8", size: "22", autoScroll: true } } });
    expect(prefs.line.toFixed(1)).toBe("1.8");
    expect(prefs.size).toBe(22);
    expect(prefs.autoScroll).toBe(true);
  });
});
