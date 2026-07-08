import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatPanel } from "./ChatPanel";

vi.mock("@/lib/api-client", () => ({
  streamChat: vi.fn(),
  forkWorkspace: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: vi.fn(),
}));

import { forkWorkspace, streamChat } from "@/lib/api-client";
import { useAuth } from "@/lib/auth";

async function* asyncEvents(events: { event: string; message: string }[]) {
  for (const evt of events) {
    yield evt;
  }
}

describe("ChatPanel", () => {
  beforeEach(() => {
    vi.mocked(useAuth).mockReturnValue({
      userId: "user-1",
      token: "jwt",
      isLoading: false,
      error: null,
      refresh: vi.fn(),
    });
    vi.mocked(streamChat).mockReset();
    vi.mocked(forkWorkspace).mockReset();
  });

  it("renders the panel, header, and empty state", () => {
    render(<ChatPanel sessionId={null} workspaceId={null} onDagEvent={vi.fn()} />);

    expect(screen.getByTestId("chat-panel")).toBeInTheDocument();
    expect(screen.getByText("OSW Workbench")).toBeInTheDocument();
    expect(screen.getByText(/Nenhuma mensagem/i)).toBeInTheDocument();
  });

  it("disables the send button until a real session id is available", () => {
    render(<ChatPanel sessionId={null} workspaceId={null} onDagEvent={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Enviar/i })).toBeDisabled();
  });

  it("streams a chat response, updates the agent bubble, and forwards DAG events", async () => {
    const user = userEvent.setup();
    vi.mocked(streamChat).mockReturnValue(
      asyncEvents([
        { event: "planning", message: "Initiating MCTS agent loop..." },
        { event: "executing", message: "Hello" },
        { event: "completed", message: "Hello world" },
      ])
    );
    const onDagEvent = vi.fn();

    render(<ChatPanel sessionId="session-1" workspaceId="workspace-1" onDagEvent={onDagEvent} />);

    await user.type(screen.getByPlaceholderText(/Digite sua query cientifica/i), "Run analysis");
    await user.click(screen.getByRole("button", { name: /Enviar/i }));

    await waitFor(() => expect(screen.getByText("Hello world")).toBeInTheDocument());

    expect(streamChat).toHaveBeenCalledWith("session-1", "Run analysis");
    expect(onDagEvent).toHaveBeenCalledWith("planning");
    expect(onDagEvent).toHaveBeenCalledWith("completed");
    expect(screen.getByText("Você")).toBeInTheDocument();
    expect(screen.getByText("Orquestrador OSW")).toBeInTheDocument();
  });

  it("forks the workspace and shows a success state instead of a browser alert()", async () => {
    const user = userEvent.setup();
    vi.mocked(forkWorkspace).mockResolvedValueOnce({
      id: "child-1",
      owner_id: "owner-1",
      fs_mount_path: "workspace_fork_abc",
      is_fork: true,
      parent_workspace_id: "workspace-1",
    });
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});

    render(<ChatPanel sessionId="session-1" workspaceId="workspace-1" onDagEvent={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /Fork/i }));

    await waitFor(() => expect(screen.getByTestId("fork-success")).toBeInTheDocument());
    expect(screen.getByTestId("fork-success").textContent).toContain("workspace_fork_abc");
    expect(forkWorkspace).toHaveBeenCalledWith(
      "workspace-1",
      expect.stringMatching(/^workspace_fork_/)
    );
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("shows an error state when the fork request fails", async () => {
    const user = userEvent.setup();
    vi.mocked(forkWorkspace).mockRejectedValueOnce(new Error("Parent workspace not found."));

    render(<ChatPanel sessionId="session-1" workspaceId="workspace-1" onDagEvent={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /Fork/i }));

    await waitFor(() => expect(screen.getByTestId("fork-error")).toBeInTheDocument());
    expect(screen.getByTestId("fork-error").textContent).toContain("Parent workspace not found.");
  });
});
