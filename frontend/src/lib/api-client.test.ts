import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  apiFetch,
  createSession,
  forkWorkspace,
  getApiBaseUrl,
  getSession,
  issueAuthToken,
  setAuthToken,
  streamChat,
} from "./api-client";

function jsonResponse(body: unknown, init: { status?: number; statusText?: string } = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    statusText: init.statusText ?? "OK",
    headers: { "Content-Type": "application/json" },
  });
}

describe("api-client", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    setAuthToken(null);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    delete process.env.NEXT_PUBLIC_API_URL;
  });

  describe("getApiBaseUrl", () => {
    it("defaults to http://localhost:8000 when NEXT_PUBLIC_API_URL is unset", () => {
      delete process.env.NEXT_PUBLIC_API_URL;
      expect(getApiBaseUrl()).toBe("http://localhost:8000");
    });

    it("honors NEXT_PUBLIC_API_URL when set", () => {
      process.env.NEXT_PUBLIC_API_URL = "https://api.example.org";
      expect(getApiBaseUrl()).toBe("https://api.example.org");
    });
  });

  describe("apiFetch auth header", () => {
    it("does not attach an Authorization header when no token has been set", async () => {
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse({ ok: true }));

      await apiFetch("/api/v1/whatever");

      const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      const headers = init.headers as Headers;
      expect(headers.has("Authorization")).toBe(false);
    });

    it("attaches 'Authorization: Bearer <token>' to every request once a token is set", async () => {
      setAuthToken("test-jwt-token");
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse({ ok: true }));

      await apiFetch("/api/v1/whatever");

      const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      const headers = init.headers as Headers;
      expect(url).toBe("http://localhost:8000/api/v1/whatever");
      expect(headers.get("Authorization")).toBe("Bearer test-jwt-token");
    });

    it("throws an ApiError with the backend's detail message on a non-2xx response", async () => {
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
        jsonResponse({ detail: "Workspace not found" }, { status: 400, statusText: "Bad Request" })
      );

      await expect(apiFetch("/api/v1/workspaces/x/fork")).rejects.toThrow("Workspace not found");

      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
        jsonResponse({ detail: "Workspace not found" }, { status: 400, statusText: "Bad Request" })
      );
      try {
        await apiFetch("/api/v1/workspaces/x/fork");
        expect.unreachable("apiFetch should have thrown on a 400 response");
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError);
        expect((err as ApiError).status).toBe(400);
      }
    });
  });

  describe("typed endpoint methods", () => {
    it("issueAuthToken posts user_id/iam_role and returns the token payload", async () => {
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
        jsonResponse({ access_token: "abc123", token_type: "bearer" })
      );

      const result = await issueAuthToken("user-1", "scientist");

      const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      expect(url).toBe("http://localhost:8000/api/v1/auth/token");
      expect(init.method).toBe("POST");
      expect(JSON.parse(init.body as string)).toEqual({ user_id: "user-1", iam_role: "scientist" });
      expect(result).toEqual({ access_token: "abc123", token_type: "bearer" });
    });

    it("createSession posts user_id/workspace_id", async () => {
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
        jsonResponse({ id: "s1", workspace_id: "w1", session_status: "INITIALIZING" })
      );

      const result = await createSession("user-1", "workspace-1");

      const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      expect(url).toBe("http://localhost:8000/api/v1/sessions");
      expect(JSON.parse(init.body as string)).toEqual({
        user_id: "user-1",
        workspace_id: "workspace-1",
      });
      expect(result.session_status).toBe("INITIALIZING");
    });

    it("getSession fetches by id", async () => {
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
        jsonResponse({ id: "s1", workspace_id: "w1", session_status: "RUNNING" })
      );

      await getSession("s1");

      const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      expect(url).toBe("http://localhost:8000/api/v1/sessions/s1");
    });

    it("forkWorkspace posts child_mount_path to the workspace fork route", async () => {
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
        jsonResponse({
          id: "child-1",
          owner_id: "owner-1",
          fs_mount_path: "workspace_fork_abc",
          is_fork: true,
          parent_workspace_id: "parent-1",
        })
      );

      const result = await forkWorkspace("parent-1", "workspace_fork_abc");

      const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      expect(url).toBe("http://localhost:8000/api/v1/workspaces/parent-1/fork");
      expect(JSON.parse(init.body as string)).toEqual({ child_mount_path: "workspace_fork_abc" });
      expect(result.is_fork).toBe(true);
    });
  });

  describe("streamChat", () => {
    function sseStreamResponse(frames: string[]): Response {
      const encoder = new TextEncoder();
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          for (const frame of frames) {
            controller.enqueue(encoder.encode(frame));
          }
          controller.close();
        },
      });
      return new Response(stream, { status: 200 });
    }

    it("parses SSE frames into ChatEvent objects, in order", async () => {
      const body = [
        'data: {"event": "planning", "message": "Initiating..."}\n\n',
        'data: {"event": "executing", "message": "Hello"}\n\n',
        'data: {"event": "completed", "message": "Hello world"}\n\n',
      ].join("");
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(sseStreamResponse([body]));

      const events = [];
      for await (const evt of streamChat("session-1", "hi")) {
        events.push(evt);
      }

      expect(events).toEqual([
        { event: "planning", message: "Initiating..." },
        { event: "executing", message: "Hello" },
        { event: "completed", message: "Hello world" },
      ]);
    });

    it("buffers a data: line split across two separate stream chunks", async () => {
      // Simulates the network delivering the SSE frame in two pieces, with the
      // split landing mid-line -- the naive line-splitting the previous inline
      // implementation used would drop/garble this frame.
      const fullLine = 'data: {"event": "completed", "message": "done"}\n\n';
      const splitPoint = 20;
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
        sseStreamResponse([fullLine.slice(0, splitPoint), fullLine.slice(splitPoint)])
      );

      const events = [];
      for await (const evt of streamChat("session-1", "hi")) {
        events.push(evt);
      }

      expect(events).toEqual([{ event: "completed", message: "done" }]);
    });
  });
});
