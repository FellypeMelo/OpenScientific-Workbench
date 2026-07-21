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
 * Shared `text/event-stream` line-reading loop, extracted so both `streamChat`
 * (below) and `streamTask` (see `types.ts`'s `BackendDAGNode` / `TaskEvent`)
 * parse SSE frames identically instead of duplicating the buffering logic.
 *
 * Buffers partial chunks across `reader.read()` calls (a stream chunk boundary
 * is not guaranteed to land on a line boundary) and parses every `data: ` line
 * as JSON, skipping malformed frames rather than aborting the whole stream.
 */
async function* readSSE<T>(response: Response): AsyncGenerator<T, void, unknown> {
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
          yield JSON.parse(line.slice("data: ".length)) as T;
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
 * `POST /api/v1/sessions/{session_id}/chat` -- consumes the `text/event-stream`
 * response from `backend/src/presentation/routes/chat.py` and yields one parsed
 * `ChatEvent` per `data: ` frame.
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
  yield* readSSE<ChatEvent>(response);
}

/** A single sub-task node exactly as serialized by the backend's
 * `DAGNode.model_dump()` (see `backend/src/domain/entities/dag.py`). */
export interface BackendDAGNode {
  id: string;
  description: string;
  dependencies: string[];
  reward: number | null;
  status: "PENDING" | "COMPLETED" | "PRUNED" | string;
  output?: Record<string, unknown> | null;
  expected?: Record<string, unknown> | null;
}

/**
 * One SSE frame emitted by `POST /api/v1/sessions/{session_id}/tasks` (see
 * `backend/src/presentation/routes/tasks.py`), which wires the MCTS-over-DAG
 * orchestrator + actor-critic reviewer into a live streamed run.
 */
export type TaskEvent =
  | { event: "dag_planned"; nodes: BackendDAGNode[]; edges: [string, string][]; tokens_spent: number; budget_exhausted: boolean; completed: boolean }
  | { event: "node_start"; node: BackendDAGNode }
  | { event: "node_update"; node: BackendDAGNode }
  | { event: "review"; approved: boolean; reason: string; attempt: number; max_attempts: number }
  | {
      event: "completed";
      session_status: string;
      dag_snapshot: Record<string, unknown>;
      dag_generation_attempts: number;
    }
  | { event: "error"; message: string };

/**
 * `POST /api/v1/sessions/{session_id}/tasks` -- consumes the `text/event-stream`
 * response from `backend/src/presentation/routes/tasks.py` and yields one parsed
 * `TaskEvent` per `data: ` frame. This is the live MCTS run (RF-001/RF-002),
 * distinct from `streamChat`'s plain conversational SSE stream.
 */
export async function* streamTask(
  sessionId: string,
  task: string,
  provider: string = "deepseek",
  signal?: AbortSignal
): AsyncGenerator<TaskEvent, void, unknown> {
  const response = await apiFetch(`/api/v1/sessions/${sessionId}/tasks`, {
    method: "POST",
    body: JSON.stringify({ task, provider }),
    signal,
  });
  yield* readSSE<TaskEvent>(response);
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

/** A single critic comment exactly as serialized by the backend's
 * `CriticComment` (see `backend/src/domain/entities/manuscript.py`). */
export interface BackendCriticComment {
  id: string;
  target_text: string;
  suggestion: string;
  resolved?: boolean;
}

interface CritiqueResponse {
  comments: BackendCriticComment[];
}

/**
 * `POST /api/v1/manuscript/critique` -- see
 * `backend/src/presentation/routes/manuscript.py`. Runs `latexSource` through
 * a real BYOK-LLM critic (RF-008) and returns its comments; throws `ApiError`
 * (400 unsupported/missing-key provider, 502 when the critic's response
 * could not be used).
 */
export async function critiqueManuscript(
  latexSource: string,
  provider: string = "deepseek"
): Promise<BackendCriticComment[]> {
  const response = await apiFetch("/api/v1/manuscript/critique", {
    method: "POST",
    body: JSON.stringify({ latex_source: latexSource, provider }),
  });
  const data: CritiqueResponse = await response.json();
  return data.comments;
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
  streamTask,
  compileManuscript,
  critiqueManuscript,
};

export default apiClient;
