"use client";

/**
 * Minimal client-side auth flow (Fase 5 - frontend gap closure).
 *
 * Design decision / reasoning:
 * There is no password/login use case anywhere in this codebase's domain model
 * (`backend/src/domain/entities/user.py` has no password field) -- this is a BYOK
 * (Bring-Your-Own-Key) internal scientific tool where the trust boundary is "you
 * can reach this deployment", not "you proved who you are". Since Fase 2 added a
 * global JWT auth middleware requiring a bearer token on every route, the
 * frontend needs *some* way to obtain a token, so this implements the minimal
 * flow that matches the backend's dev-mode issuance endpoint
 * (`POST /api/v1/auth/token`, see `backend/src/presentation/routes/auth.py`):
 *   1. Generate (once) a random UUID identifying this browser as a "user",
 *      persisted in `localStorage` so it survives reloads.
 *   2. On first load, exchange that id for a signed JWT via the token endpoint.
 *   3. Keep the token in memory (React state) + `localStorage`, and push it into
 *      `api-client.ts`'s module-level singleton so every API call is
 *      authenticated automatically.
 *
 * This is intentionally a plain React Context, not Redux/Zustand/etc. -- the
 * amount of state here (a user id, a token, a loading/error flag) does not
 * warrant a global store library.
 *
 * Explicitly NOT implemented (future scope, see Fase 5 in
 * `docs/planning/execution_plan_gap_closure.md`): password/OAuth/SSO login,
 * token refresh/rotation, multi-user switching in one browser, or server-side
 * session validation beyond the JWT's own expiry.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { issueAuthToken, setAuthToken as setApiClientAuthToken } from "./api-client";

const LOCAL_USER_ID_KEY = "osw.userId";
const LOCAL_TOKEN_KEY = "osw.authToken";

function generateUuid(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // Fallback for environments without `crypto.randomUUID` (older browsers /
  // some test runners). Not cryptographically strong, but this id is only ever
  // used as an opaque BYOK "who is asking" tag, never a security credential.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/** Reads (or lazily creates) the local, `localStorage`-persisted user id. */
export function getOrCreateLocalUserId(): string {
  if (typeof window === "undefined") {
    // SSR pass: nothing is persisted here, the client-side effect resolves the
    // real, persisted value once mounted in the browser.
    return generateUuid();
  }
  const existing = window.localStorage.getItem(LOCAL_USER_ID_KEY);
  if (existing) return existing;

  const created = generateUuid();
  window.localStorage.setItem(LOCAL_USER_ID_KEY, created);
  return created;
}

interface AuthState {
  userId: string | null;
  token: string | null;
  isLoading: boolean;
  error: string | null;
}

interface AuthContextValue extends AuthState {
  /** Re-runs the token acquisition flow (e.g. after a manual retry click). */
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    userId: null,
    token: null,
    isLoading: true,
    error: null,
  });

  const acquireToken = useCallback(async () => {
    setState((s) => ({ ...s, isLoading: true, error: null }));
    try {
      const userId = getOrCreateLocalUserId();
      const { access_token: token } = await issueAuthToken(userId);

      setApiClientAuthToken(token);
      if (typeof window !== "undefined") {
        window.localStorage.setItem(LOCAL_TOKEN_KEY, token);
      }
      setState({ userId, token, isLoading: false, error: null });
    } catch (err) {
      setApiClientAuthToken(null);
      setState((s) => ({
        ...s,
        isLoading: false,
        error: err instanceof Error ? err.message : "Failed to authenticate.",
      }));
    }
  }, []);

  useEffect(() => {
    acquireToken();
  }, [acquireToken]);

  const value = useMemo<AuthContextValue>(
    () => ({ ...state, refresh: acquireToken }),
    [state, acquireToken]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an <AuthProvider>.");
  }
  return ctx;
}
