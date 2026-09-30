import React from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api.js", () => ({
  authApi: {
    providers: vi.fn(),
    login: vi.fn(),
    register: vi.fn(),
    requestReset: vi.fn(),
    reset: vi.fn(),
    verify: vi.fn(),
    me: vi.fn(),
    oauthStart: vi.fn(),
  },
}));
vi.mock("../../App.jsx", () => ({ useTheme: () => ({ theme: "dark", setTheme: vi.fn() }) }));

import { authApi } from "./api.js";
import { AuthScreen } from "./AuthScreen.jsx";

function Where() {
  const location = useLocation();
  return <div data-testid="where">{location.pathname}</div>;
}

function renderAt(path, onAuthed = vi.fn()) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="*" element={<><AuthScreen onAuthed={onAuthed} /><Where /></>} />
      </Routes>
    </MemoryRouter>,
  );
  return onAuthed;
}

/* The e2e contract: the exact text "Password" is an element whose parent holds the input. */
function passwordInput() {
  return screen.getByText("Password", { exact: true }).parentElement.querySelector("input");
}

beforeEach(() => {
  // jsdom has no WebGL/2D canvas: the ocean falls back to its CSS sea.
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => null);
  authApi.providers.mockResolvedValue({ providers: ["google", "discord"] });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("AuthScreen — sign in", () => {
  it("keeps the sign-in contract and signs in with trimmed credentials", async () => {
    const user = { id: 1, username: "reader" };
    authApi.login.mockResolvedValue(user);
    const onAuthed = renderAt("/login");

    expect(screen.getByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Tideglass" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/email or username/i), { target: { value: "  reader  " } });
    expect(passwordInput()).toHaveAttribute("type", "password");
    fireEvent.change(passwordInput(), { target: { value: "secret-password" } });
    const submit = screen.getAllByRole("button", { name: /sign in/i });
    expect(submit).toHaveLength(1);
    fireEvent.click(submit[0]);

    await waitFor(() => expect(onAuthed).toHaveBeenCalledWith(user));
    expect(authApi.login).toHaveBeenCalledWith("reader", "secret-password");
  });

  it("offers each configured provider as a pill that starts OAuth", async () => {
    renderAt("/login");
    const google = await screen.findByRole("button", { name: "Google" });
    expect(screen.getByRole("button", { name: "Discord" })).toBeInTheDocument();
    expect(screen.getByText("or continue with")).toBeInTheDocument();
    fireEvent.click(google);
    expect(authApi.oauthStart).toHaveBeenCalledWith("google");
  });

  it("reveals the password with a keyboard-reachable toggle that reports its state", () => {
    renderAt("/login");
    expect(passwordInput()).toHaveAccessibleName("Password");
    const toggle = screen.getByRole("button", { name: "Show password" });
    expect(toggle).not.toHaveAttribute("tabindex");
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    expect(passwordInput()).toHaveAttribute("type", "text");
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(toggle);
    expect(passwordInput()).toHaveAttribute("type", "password");
    expect(toggle).toHaveAttribute("aria-pressed", "false");
  });

  it("keeps the failed-provider message from ?error=oauth visible", async () => {
    renderAt("/login?error=oauth");
    expect(screen.getByRole("alert")).toHaveTextContent("Sign-in with that provider failed.");
    await screen.findByRole("button", { name: "Google" });
    expect(screen.getByRole("alert")).toHaveTextContent("Sign-in with that provider failed.");
  });

  it("surfaces a rejected sign-in as an alert", async () => {
    authApi.login.mockRejectedValue(new Error("Wrong username or password."));
    const onAuthed = renderAt("/login");
    fireEvent.change(screen.getByLabelText(/email or username/i), { target: { value: "reader" } });
    fireEvent.change(passwordInput(), { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong username or password.");
    expect(onAuthed).not.toHaveBeenCalled();
  });

  it("links to recovery and registration", async () => {
    renderAt("/login");
    fireEvent.click(screen.getByRole("button", { name: "Create an account" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/register"));
    expect(await screen.findByRole("heading", { name: "Create your account" })).toBeInTheDocument();
  });
});

describe("AuthScreen — register", () => {
  it("labels every field, validates in place and registers", async () => {
    const user = { id: 2, username: "new_reader" };
    authApi.register.mockResolvedValue(user);
    const onAuthed = renderAt("/register");

    const email = screen.getByLabelText("Email");
    const username = screen.getByLabelText("Username");
    expect(passwordInput()).toHaveAttribute("autocomplete", "new-password");

    fireEvent.change(email, { target: { value: "not-an-email" } });
    fireEvent.blur(email);
    fireEvent.change(username, { target: { value: "A!" } });
    fireEvent.blur(username);
    fireEvent.change(passwordInput(), { target: { value: "short" } });
    expect(await screen.findByText("That doesn't look like an email address.")).toBeInTheDocument();
    expect(screen.getByText("3–24 characters: a–z, 0–9, underscore.")).toBeInTheDocument();
    expect(screen.getByText("At least 8 characters.")).toBeInTheDocument();
    // Errors describe the field (and mark it invalid) without joining its name.
    expect(email).toHaveAccessibleName("Email");
    expect(email).toHaveAttribute("aria-invalid", "true");
    expect(email).toHaveAccessibleDescription("That doesn't look like an email address.");
    expect(username).toHaveAccessibleDescription("3–24 characters: a–z, 0–9, underscore.");
    expect(passwordInput()).toHaveAccessibleName("Password");
    expect(passwordInput()).toHaveAttribute("aria-invalid", "true");
    expect(passwordInput()).toHaveAccessibleDescription("At least 8 characters.");

    fireEvent.change(email, { target: { value: " reader@example.test " } });
    fireEvent.change(username, { target: { value: "new_reader" } });
    fireEvent.change(passwordInput(), { target: { value: "long-enough" } });
    expect(await screen.findByText("Looks good.")).toBeInTheDocument();
    expect(email).toHaveAttribute("aria-invalid", "false");
    expect(email).not.toHaveAttribute("aria-describedby");
    expect(passwordInput()).toHaveAttribute("aria-invalid", "false");
    expect(passwordInput()).toHaveAccessibleDescription("Looks good.");
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => expect(onAuthed).toHaveBeenCalledWith(user));
    expect(authApi.register).toHaveBeenCalledWith("reader@example.test", "new_reader", "long-enough");
  });
});

describe("AuthScreen — recovery and verification", () => {
  it.each([
    ["/forgot", "Reset your password", "Send reset link"],
    ["/reset?token=abc", "Set a new password", "Update password"],
    ["/verify?token=abc", "Verify your email", "Verify email"],
  ])("%s shows its title and action", (path, title, action) => {
    renderAt(path);
    expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: action })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /back to sign in/i })).toBeInTheDocument();
  });

  it("explains a failed verification with a way back", () => {
    renderAt("/verify-failed");
    expect(screen.getByRole("heading", { name: "Verification failed" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("That verification link is invalid or expired.");
    expect(screen.getByRole("button", { name: /back to sign in/i })).toBeInTheDocument();
  });

  it("asks for a verification token before verifying", () => {
    renderAt("/verify");
    expect(screen.getByRole("status")).toHaveTextContent("Confirm your email to finish verification.");
    expect(screen.getByRole("button", { name: "Verify email" })).toBeDisabled();
  });

  it("requests a reset link and returns to sign in with a confirmation", async () => {
    authApi.requestReset.mockResolvedValue({});
    renderAt("/forgot");
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: " reader@example.test " } });
    fireEvent.click(screen.getByRole("button", { name: "Send reset link" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/login"));
    expect(authApi.requestReset).toHaveBeenCalledWith("reader@example.test");
    expect(await screen.findByText("If that email has an account, a reset link is on its way.")).toBeInTheDocument();
  });

  it("resets the password with the link's token", async () => {
    authApi.reset.mockResolvedValue({});
    renderAt("/reset?token=tok-1");
    const input = screen.getByText("New password", { exact: true }).parentElement.querySelector("input");
    fireEvent.change(input, { target: { value: "brand-new-pass" } });
    fireEvent.click(screen.getByRole("button", { name: "Update password" }));
    await waitFor(() => expect(authApi.reset).toHaveBeenCalledWith("tok-1", "brand-new-pass"));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/login"));
  });
});
