import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NovelpiaRecoveryLinks } from "./NovelpiaRecoveryLinks.jsx";

describe("Novelpia scrape recovery links", () => {
  it("links the exact official numeric viewer URL in an ad error", () => {
    render(<NovelpiaRecoveryLinks kind="scrape" error="Novelpia requires an ad. Open https://global.novelpia.com/viewer/409763, complete the ad, then retry." />);
    const link = screen.getByRole("link", { name: "Open chapter on Novelpia" });
    expect(link).toHaveAttribute("href", "https://global.novelpia.com/viewer/409763");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
    expect(screen.queryByRole("link", { name: "Update Novelpia cookies" })).not.toBeInTheDocument();
  });

  it.each([
    "https://global.novelpia.com.evil.test/viewer/123",
    "https://global.novelpia.com@evil.test/viewer/123",
    "http://global.novelpia.com/viewer/123",
    "https://global.novelpia.com/viewer/123/evil",
    "https://global.novelpia.com/viewer/123?redirect=https://evil.test",
    "https://global.novelpia.com/viewer/123.evil",
    "https://global.novelpia.com/viewer/abc",
    "javascript:alert(1)",
  ])("does not link unapproved URLs: %s", url => {
    render(<NovelpiaRecoveryLinks kind="scrape" error={`Novelpia failed: ${url}`} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("offers cookie settings for Novelpia authentication errors", () => {
    render(<NovelpiaRecoveryLinks kind="scrape" error="Novelpia login expired or was rejected. Replace your cookies in Settings." />);
    expect(screen.getByRole("link", { name: "Update Novelpia cookies" })).toHaveAttribute("href", "/account/sources");
  });

  it.each([
    { kind: "translate", error: "Novelpia login expired." },
    { kind: "scrape", error: "Other website login expired." },
    { kind: "scrape", error: null },
  ])("does not add recovery links to unrelated errors", props => {
    render(<NovelpiaRecoveryLinks {...props} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
