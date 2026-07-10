/**
 * Small typed fetch wrapper around the FastAPI backend (`backend/src/presentation`).
 *
 * Every route in the backend is behind the globally-registered `JWTAuthMiddleware`
 * except `/docs`, `/openapi.json`, `/redoc`, and `/api/v1/auth/token` (see
 * `backend/src/presentation/middleware/jwt_auth.py`). This module keeps the current
 * bearer token in a module-level variable (set by `AuthProvider`, see
 * `frontend/src/lib/auth.tsx`) and attaches it to every request automatically, so
 * feature code never has to thread a token through call sites by hand.
 *
 * Base URL resolution: `process.env.NEXT_PUBLIC_API_URL`, defaulting to
 * `http://localhost:8000` for local development against `uvicorn` running on its
 * default port.
 */

const DEFAULT_BASE_URL = "http://localhost:8000";

export function getApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL || DEFAULT_BASE_URL;
}

// Module-level singleton holding the current bearer token. Deliberately not a
// React state value: `api-client.ts` must be usable from plain async functions
// (not just components), and there is exactly one active token per browser tab
// in this BYOK single-user-per-session model (see `lib/auth.tsx`).
let currentAuthToken: string | null = null;

export function setAuthToken(token: string | null): void {
  currentAuthToken = token;
}

export function getAuthToken(): string | null {
  return currentAuthToken;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function extractErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.clone().json();
    if (typeof body?.detail === "string") return body.detail;
    if (typeof body?.message === "string") return body.message;
  } catch {
    // Response body wasn't JSON (or was empty) -- fall through to statusText.
  }
  return response.statusText || `Request failed with status ${response.status}`;
}

/**
 * Low-level fetch wrapper: resolves the base URL, attaches the JSON content
 * type + bearer token headers, and normalizes non-2xx responses into a thrown
 * `ApiError` (instead of every call site re-checking `response.ok`).
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  if (currentAuthToken) {
    headers.set("Authorization", `Bearer ${currentAuthToken}`);
  }

  const response = await fetch(`${getApiBaseUrl()}${path}`, { ...init, headers });

  if (!response.ok) {
    throw new ApiError(await extractErrorMessage(response), response.status);
  }
  return response;
}

// --- Typed endpoint methods -------------------------------------------------

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

/** `POST /api/v1/auth/token` -- see `backend/src/presentation/routes/auth.py`. */
export async function issueAuthToken(
  userId: string,
  iamRole: string = "scientist"
): Promise<TokenResponse> {
  const response = await apiFetch("/api/v1/auth/token", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, iam_role: iamRole }),
  });
  return response.json();
}

export interface SessionResponse {
  id: string;
  workspace_id: string;
  session_status: string;
}

/** `POST /api/v1/sessions` -- see `backend/src/presentation/routes/sessions.py`. */
export async function createSession(userId: string, workspaceId: string): Promise<SessionResponse> {
  const response = await apiFetch("/api/v1/sessions", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, workspace_id: workspaceId }),
  });
  return response.json();
}

/** `GET /api/v1/sessions/{session_id}`. */
export async function getSession(sessionId: string): Promise<SessionResponse> {
  const response = await apiFetch(`/api/v1/sessions/${sessionId}`);
  return response.json();
}

export interface WorkspaceResponse {
  id: string;
  owner_id: string;
  fs_mount_path: string;
  is_fork: boolean;
  parent_workspace_id: string | null;
}

/** `POST /api/v1/workspaces/{workspace_id}/fork` -- see `backend/src/presentation/routes/workspaces.py`. */
export async function forkWorkspace(
  workspaceId: string,
  childMountPath: string
): Promise<WorkspaceResponse> {
  const response = await apiFetch(`/api/v1/workspaces/${workspaceId}/fork`, {
    method: "POST",
    body: JSON.stringify({ child_mount_path: childMountPath }),
  });
  return response.json();
}

export interface ChatEvent {
  event: "planning" | "executing" | "completed" | "error" | string;
  message: string;
}

/**
 * `POST /api/v1/sessions/{session_id}/chat` -- consumes the `text/event-stream`
 * response from `backend/src/presentation/routes/chat.py` and yields one parsed
 * `ChatEvent` per `data: ` frame.
 *
 * Buffers partial chunks across `reader.read()` calls (a `TextDecoderStream`
 * chunk boundary is not guaranteed to land on a line boundary), which the
 * original inline implementation in `app/page.tsx` did not do -- this is a
 * correctness improvement, not just a relocation.
 */
export async function* streamChat(
  sessionId: string,
  prompt: string,
  provider: string = "deepseek",
  signal?: AbortSignal
): AsyncGenerator<ChatEvent, void, unknown> {
  const response = await apiFetch(`/api/v1/sessions/${sessionId}/chat`, {
    method: "POST",
    body: JSON.stringify({ prompt, provider }),
    signal,
  });

  if (!response.body) return;

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      // The last element may be an incomplete line -- keep it buffered until
      // the next chunk arrives instead of parsing a truncated frame.
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        try {
          yield JSON.parse(line.slice("data: ".length)) as ChatEvent;
        } catch {
          // Malformed SSE frame -- skip it rather than aborting the whole stream.
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * `POST /api/v1/manuscript/compile` -- see
 * `backend/src/presentation/routes/manuscript.py`. Returns the compiled PDF as a
 * Blob; throws `ApiError` (status 503 when tectonic is unavailable, 422 on
 * invalid LaTeX).
 */
export async function compileManuscript(latexSource: string): Promise<Blob> {
  const response = await apiFetch("/api/v1/manuscript/compile", {
    method: "POST",
    body: JSON.stringify({ latex_source: latexSource }),
  });
  return response.blob();
}

export const apiClient = {
  getApiBaseUrl,
  setAuthToken,
  getAuthToken,
  issueAuthToken,
  createSession,
  getSession,
  forkWorkspace,
  streamChat,
  compileManuscript,
};

export default apiClient;
