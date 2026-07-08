import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// `page.tsx` was split into `components/ChatPanel.tsx`, `components/VisualizerPanel.tsx`,
// and `components/MCTSGraph.tsx` (see docs/planning/execution_plan_gap_closure.md Fase 5).
// This file now only tests `Home`'s own composition/wiring responsibilities
// (rendering the three panels, bootstrapping a real session once auth resolves,
// and forwarding ids/state to the children) -- each child component's own
// behavior is covered by its dedicated test file
// (`ChatPanel.test.tsx`, `MCTSGraph.test.tsx`, `VisualizerPanel.test.tsx`).
vi.mock("@/lib/auth", () => ({ useAuth: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ createSession: vi.fn() }));
vi.mock("@/components/ChatPanel", () => ({
  ChatPanel: (props: { sessionId: string | null; workspaceId: string | null }) => (
    <div
      data-testid="chat-panel"
      data-session-id={props.sessionId ?? ""}
      data-workspace-id={props.workspaceId ?? ""}
    />
  ),
}));
vi.mock("@/components/VisualizerPanel", () => ({
  VisualizerPanel: () => <div data-testid="visualizer-panel" />,
}));
vi.mock("@/components/MCTSGraph", () => ({
  MCTSGraph: ({ dagNodes }: { dagNodes: unknown[] }) => (
    <div data-testid="mcts-graph" data-node-count={dagNodes.length} />
  ),
}));

import { createSession } from "@/lib/api-client";
import { useAuth } from "@/lib/auth";

import Home from "./page";

describe("Home page", () => {
  beforeEach(() => {
    window.localStorage.clear();
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
});
