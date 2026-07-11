import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(resolve(process.cwd(), "src/app/Root.jsx"), "utf8");

describe("browser route contract", () => {
  const routes = [
    "/", "/library", "/discover", "/import", "/jobs", "/u/:username",
    "/account", "/account/:section", "/admin", "/admin/:tab",
    "/n/:novelId", "/n/:novelId/read/:number", "/login", "/register",
  ];

  it.each(routes)("keeps %s", (path) => {
    expect(source).toContain(`path="${path}"`);
  });

  it("keeps auth recovery and legacy hash compatibility keys", () => {
    for (const key of ["nw-return-to", "/forgot", "/reset", "/verify", "/verify-failed"]) {
      expect(source).toContain(key);
    }
  });
});
