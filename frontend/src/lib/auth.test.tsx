import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, getOrCreateLocalUserId, useAuth } from "./auth";

vi.mock("./api-client", () => ({
  issueAuthToken: vi.fn(),
  setAuthToken: vi.fn(),
}));

import { issueAuthToken, setAuthToken } from "./api-client";

function Consumer() {
  const { userId, token, isLoading, error } = useAuth();
  return (
    <div>
      <span data-testid="user-id">{userId ?? "none"}</span>
      <span data-testid="token">{token ?? "none"}</span>
      <span data-testid="loading">{String(isLoading)}</span>
      <span data-testid="error">{error ?? "none"}</span>
    </div>
  );
}

describe("auth", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.mocked(issueAuthToken).mockReset();
    vi.mocked(setAuthToken).mockReset();
  });

  describe("getOrCreateLocalUserId", () => {
    it("creates and persists a UUID in localStorage on first call", () => {
      expect(window.localStorage.getItem("osw.userId")).toBeNull();
      const id = getOrCreateLocalUserId();
      expect(id).toMatch(/^[0-9a-f-]{36}$/i);
      expect(window.localStorage.getItem("osw.userId")).toBe(id);
    });

    it("reuses the persisted id on subsequent calls", () => {
      const first = getOrCreateLocalUserId();
      const second = getOrCreateLocalUserId();
      expect(second).toBe(first);
    });
  });

  describe("AuthProvider / useAuth", () => {
    it("acquires a token on mount and stores it in localStorage + api-client", async () => {
      vi.mocked(issueAuthToken).mockResolvedValueOnce({
        access_token: "jwt-abc",
        token_type: "bearer",
      });

      render(
        <AuthProvider>
          <Consumer />
        </AuthProvider>
      );

      expect(screen.getByTestId("loading").textContent).toBe("true");

      await waitFor(() => expect(screen.getByTestId("loading").textContent).toBe("false"));

      expect(screen.getByTestId("token").textContent).toBe("jwt-abc");
      expect(screen.getByTestId("user-id").textContent).not.toBe("none");
      expect(setAuthToken).toHaveBeenCalledWith("jwt-abc");
      expect(window.localStorage.getItem("osw.authToken")).toBe("jwt-abc");

      // The user id sent to the token endpoint is the same one persisted
      // locally, proving the localStorage-persisted id round-trips through to
      // the backend call.
      const persistedUserId = window.localStorage.getItem("osw.userId");
      expect(issueAuthToken).toHaveBeenCalledWith(persistedUserId);
    });

    it("surfaces a readable error and clears the api-client token when issuance fails", async () => {
      vi.mocked(issueAuthToken).mockRejectedValueOnce(new Error("network down"));

      render(
        <AuthProvider>
          <Consumer />
        </AuthProvider>
      );

      await waitFor(() => expect(screen.getByTestId("loading").textContent).toBe("false"));

      expect(screen.getByTestId("error").textContent).toBe("network down");
      expect(screen.getByTestId("token").textContent).toBe("none");
      expect(setAuthToken).toHaveBeenCalledWith(null);
    });

    it("throws when useAuth is used outside of an AuthProvider", () => {
      // Swallow the expected React error-boundary console noise for this
      // negative-path assertion.
      const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      expect(() => render(<Consumer />)).toThrow(/useAuth must be used within an <AuthProvider>/);
      consoleSpy.mockRestore();
    });
  });
});
