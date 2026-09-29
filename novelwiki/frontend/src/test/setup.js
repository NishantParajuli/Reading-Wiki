import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => cleanup());

// vi.fn(impl) — not vi.fn().mockImplementation(impl) — so `restoreMocks` restores
// this implementation between tests instead of leaving a mock returning undefined.
function matchMediaImpl(query) {
  return {
    matches: false,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() { return false; },
  };
}
Object.defineProperty(window, "matchMedia", { writable: true, configurable: true, value: vi.fn(matchMediaImpl) });

window.scrollTo = vi.fn();
