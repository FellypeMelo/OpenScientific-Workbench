import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TaskEvent } from "@/lib/api-client";

// `page.tsx` was split into `components/ChatPanel.tsx`, `components/VisualizerPanel.tsx`,
// and `components/MCTSGraph.tsx` (see docs/planning/execution_plan_gap_closure.md Fase 5).
// This file now only tests `Home`'s own composition/wiring responsibilities
// (rendering the three panels, bootstrapping a real session once auth resolves,
// forwarding ids/state to the children, and mapping real MCTS task-execution SSE
// events onto DAG node state + the review-status strip) -- each child
// component's own rendering behavior is covered by its dedicated test file
// (`ChatPanel.test.tsx`, `MCTSGraph.test.tsx`, `VisualizerPanel.test.tsx`).
vi.mock("@/lib/auth", () => ({ useAuth: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ createSession: vi.fn() }));

// Captures the `onTaskEvent` callback `Home` passes to `ChatPanel` so tests can
// drive it directly, exactly as a real streamed SSE event would.
let capturedOnTaskEvent: ((event: TaskEvent) => void) | undefined;

vi.mock("@/components/ChatPanel", () => ({
  ChatPanel: (props: {
    sessionId: string | null;
    workspaceId: string | null;
    onTaskEvent?: (event: TaskEvent) => void;
  }) => {
    capturedOnTaskEvent = props.onTaskEvent;
    return (
      <div
        data-testid="chat-panel"
        data-session-id={props.sessionId ?? ""}
        data-workspace-id={props.workspaceId ?? ""}
      />
    );
  },
}));
vi.mock("@/components/VisualizerPanel", () => ({
  // Serializes the `result` prop `Home` computed (RF-007), so tests can
  // assert on the real node_update -> extractVisualization -> setVisualization
  // wiring without re-testing VisualizerPanel's own rendering (covered by
  // VisualizerPanel.test.tsx).
  VisualizerPanel: ({ result }: { result?: Record<string, unknown> }) => (
    <div data-testid="visualizer-panel" data-result={JSON.stringify(result ?? null)} />
  ),
}));
vi.mock("@/components/MCTSGraph", () => ({
  // Serializes the exact DAGNode objects Home computed, so tests can assert on
  // the real event -> node mapping (mapBackendNode) without re-testing
  // MCTSGraph's own rendering (covered by MCTSGraph.test.tsx).
  MCTSGraph: ({ dagNodes }: { dagNodes: unknown[] }) => (
    <div
      data-testid="mcts-graph"
      data-node-count={dagNodes.length}
      data-nodes={JSON.stringify(dagNodes)}
    />
  ),
}));

import { createSession } from "@/lib/api-client";
import { useAuth } from "@/lib/auth";

import Home from "./page";

describe("Home page", () => {
  beforeEach(() => {
    window.localStorage.clear();
    capturedOnTaskEvent = undefined;
    vi.mocked(useAuth).mockReturnValue({
      userId: "user-1",
      token: "jwt",
      isLoading: false,
      error: null,
      refresh: vi.fn(),
    });
    vi.mocked(createSession).mockReset();
  });

  it("renders the three-panel layout via the split components", () => {
    vi.mocked(createSession).mockReturnValue(new Promise(() => {})); // pending forever
    render(<Home />);

    expect(screen.getByTestId("chat-panel")).toBeInTheDocument();
    expect(screen.getByTestId("visualizer-panel")).toBeInTheDocument();
    expect(screen.getByTestId("dag-panel")).toBeInTheDocument();
    expect(screen.getByTestId("mcts-graph")).toBeInTheDocument();
  });

  it("starts with no DAG nodes -- real task-execution events populate it, not a fake demo", () => {
    vi.mocked(createSession).mockReturnValue(new Promise(() => {}));
    render(<Home />);

    expect(screen.getByTestId("mcts-graph").dataset.nodeCount).toBe("0");
  });

  it("provisions a real session once auth resolves and forwards the ids to ChatPanel", async () => {
    vi.mocked(createSession).mockResolvedValueOnce({
      id: "session-xyz",
      workspace_id: "workspace-xyz",
      session_status: "INITIALIZING",
    });

    render(<Home />);

    await waitFor(() => expect(createSession).toHaveBeenCalledTimes(1));
    expect(createSession).toHaveBeenCalledWith("user-1", expect.any(String));

    await waitFor(() =>
      expect(screen.getByTestId("chat-panel").dataset.sessionId).toBe("session-xyz")
    );
    expect(screen.getByTestId("chat-panel").dataset.workspaceId).toBe("workspace-xyz");
  });

  it("does not attempt to create a session while auth is still loading", () => {
    vi.mocked(useAuth).mockReturnValue({
      userId: null,
      token: null,
      isLoading: true,
      error: null,
      refresh: vi.fn(),
    });

    render(<Home />);

    expect(createSession).not.toHaveBeenCalled();
    expect(screen.getByTestId("chat-panel").dataset.sessionId).toBe("");
  });

  it("surfaces a session provisioning error near the DAG panel", async () => {
    vi.mocked(createSession).mockRejectedValueOnce(new Error("Workspace not found"));

    render(<Home />);

    expect(await screen.findByTestId("session-error")).toHaveTextContent("Workspace not found");
  });

  describe("real MCTS task-execution event wiring", () => {
    function renderAndWaitForHandler() {
      vi.mocked(createSession).mockReturnValue(new Promise(() => {}));
      render(<Home />);
      expect(capturedOnTaskEvent).toBeTypeOf("function");
    }

    it("dag_planned populates DAG nodes, mapping backend description onto label", () => {
      renderAndWaitForHandler();

      act(() => {
        capturedOnTaskEvent!({
          event: "dag_planned",
          nodes: [
            { id: "n1", description: "load sequence data", dependencies: [], reward: null, status: "PENDING" },
            { id: "n2", description: "run alignment", dependencies: ["n1"], reward: null, status: "PENDING" },
          ],
          edges: [["n1", "n2"]],
          tokens_spent: 0,
          budget_exhausted: false,
          completed: false,
        });
      });

      const nodes = JSON.parse(screen.getByTestId("mcts-graph").dataset.nodes ?? "[]");
      expect(nodes).toEqual([
        { id: "n1", label: "load sequence data", status: "pending", parentId: undefined },
        { id: "n2", label: "run alignment", status: "pending", parentId: "n1" },
      ]);
    });

    it("node_start marks the node running, node_update reflects its resolved backend status", () => {
      renderAndWaitForHandler();

      act(() => {
        capturedOnTaskEvent!({
          event: "dag_planned",
          nodes: [{ id: "n1", description: "load data", dependencies: [], reward: null, status: "PENDING" }],
          edges: [],
          tokens_spent: 0,
          budget_exhausted: false,
          completed: false,
        });
      });
      act(() => {
        capturedOnTaskEvent!({
          event: "node_start",
          node: { id: "n1", description: "load data", dependencies: [], reward: null, status: "PENDING" },
        });
      });

      let nodes = JSON.parse(screen.getByTestId("mcts-graph").dataset.nodes ?? "[]");
      expect(nodes[0].status).toBe("running");

      act(() => {
        capturedOnTaskEvent!({
          event: "node_update",
          node: {
            id: "n1",
            description: "load data",
            dependencies: [],
            reward: 1.0,
            status: "COMPLETED",
            output: { text: "ok" },
          },
        });
      });

      nodes = JSON.parse(screen.getByTestId("mcts-graph").dataset.nodes ?? "[]");
      expect(nodes[0].status).toBe("success");
    });

    it("an approved review shows the approved state on the review-status strip", () => {
      renderAndWaitForHandler();

      act(() => {
        capturedOnTaskEvent!({ event: "review", approved: true, reason: "ok", attempt: 1, max_attempts: 3 });
      });

      const strip = screen.getByTestId("review-status-strip");
      expect(strip.dataset.status).toBe("approved");
    });

    it("a rejection under the attempt cap shows the rejected-and-retrying state", () => {
      renderAndWaitForHandler();

      act(() => {
        capturedOnTaskEvent!({
          event: "review",
          approved: false,
          reason: "numeric divergence",
          attempt: 1,
          max_attempts: 3,
        });
      });

      const strip = screen.getByTestId("review-status-strip");
      expect(strip.dataset.status).toBe("retrying");
      expect(strip.textContent).toContain("numeric divergence");
    });

    it("a rejection on the last allowed attempt shows the final-rejection state", () => {
      renderAndWaitForHandler();

      act(() => {
        capturedOnTaskEvent!({
          event: "review",
          approved: false,
          reason: "numeric divergence",
          attempt: 3,
          max_attempts: 3,
        });
      });

      const strip = screen.getByTestId("review-status-strip");
      expect(strip.dataset.status).toBe("final-rejection");
    });

    it("starts with no visualization data -- the panel gets undefined until a real result arrives (RF-007)", () => {
      renderAndWaitForHandler();

      expect(screen.getByTestId("visualizer-panel").dataset.result).toBe("null");
    });

    it("a node_update carrying a recognizable structure reference populates the visualizer panel", () => {
      renderAndWaitForHandler();

      act(() => {
        capturedOnTaskEvent!({
          event: "node_update",
          node: {
            id: "n1",
            description: "fetch structure",
            dependencies: [],
            reward: 1,
            status: "COMPLETED",
            output: { stdout: '{"pdb_id": "1CRN"}', exit_code: 0 },
          },
        });
      });

      const result = JSON.parse(screen.getByTestId("visualizer-panel").dataset.result ?? "null");
      expect(result).toEqual({ pdbId: "1CRN", genome: undefined, locus: undefined });
    });

    it("a node_update with no recognizable output leaves the visualizer panel untouched", () => {
      renderAndWaitForHandler();

      act(() => {
        capturedOnTaskEvent!({
          event: "node_update",
          node: {
            id: "n1",
            description: "align reads",
            dependencies: [],
            reward: 1,
            status: "COMPLETED",
            output: { stdout: "Alignment complete.", exit_code: 0 },
          },
        });
      });

      expect(screen.getByTestId("visualizer-panel").dataset.result).toBe("null");
    });

    it("a fresh dag_planned event clears a stale visualization from a previous run", () => {
      renderAndWaitForHandler();

      act(() => {
        capturedOnTaskEvent!({
          event: "node_update",
          node: {
            id: "n1",
            description: "fetch structure",
            dependencies: [],
            reward: 1,
            status: "COMPLETED",
            output: { stdout: '{"pdb_id": "1CRN"}', exit_code: 0 },
          },
        });
      });
      expect(screen.getByTestId("visualizer-panel").dataset.result).not.toBe("null");

      act(() => {
        capturedOnTaskEvent!({
          event: "dag_planned",
          nodes: [],
          edges: [],
          tokens_spent: 0,
          budget_exhausted: false,
          completed: false,
        });
      });

      expect(screen.getByTestId("visualizer-panel").dataset.result).toBe("null");
    });

    it("an error event surfaces a task-error message near the DAG panel", () => {
      renderAndWaitForHandler();

      act(() => {
        capturedOnTaskEvent!({ event: "error", message: "The model provider stream failed." });
      });

      expect(screen.getByTestId("task-error")).toHaveTextContent(
        "The model provider stream failed."
      );
    });

    it("a fresh dag_planned event resets a stale review strip and task error", () => {
      renderAndWaitForHandler();

      act(() => {
        capturedOnTaskEvent!({ event: "error", message: "boom" });
      });
      act(() => {
        capturedOnTaskEvent!({
          event: "review",
          approved: false,
          reason: "numeric divergence",
          attempt: 3,
          max_attempts: 3,
        });
      });
      expect(screen.getByTestId("task-error")).toBeInTheDocument();
      expect(screen.getByTestId("review-status-strip")).toBeInTheDocument();

      act(() => {
        capturedOnTaskEvent!({
          event: "dag_planned",
          nodes: [],
          edges: [],
          tokens_spent: 0,
          budget_exhausted: false,
          completed: false,
        });
      });

      expect(screen.queryByTestId("task-error")).not.toBeInTheDocument();
      expect(screen.queryByTestId("review-status-strip")).not.toBeInTheDocument();
    });
  });
});
