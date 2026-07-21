"use client";

import { useState } from "react";

import { forkWorkspace, streamChat, streamTask, type TaskEvent } from "@/lib/api-client";
import { useAuth } from "@/lib/auth";

import { Header } from "./Header";
import type { Message } from "./types";

type ForkState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; path: string }
  | { status: "error"; message: string };

export interface ChatPanelProps {
  /** Real session id (created by the parent via `POST /api/v1/sessions`), or
   * `null` while it is still being provisioned. */
  sessionId: string | null;
  /** Real workspace id backing `sessionId`, used by the Fork button. */
  workspaceId: string | null;
  /** Forwards SSE lifecycle events so the parent can drive `MCTSGraph`'s node
   * statuses -- see `app/page.tsx`. */
  onDagEvent: (event: "planning" | "completed" | "error") => void;
  /** Forwards raw MCTS task-execution SSE events (RF-001/RF-002, see
   * `POST /api/v1/sessions/{session_id}/tasks`) so the parent can drive real
   * DAG node state and the actor-critic review-status strip -- see
   * `app/page.tsx`. Optional so callers that only care about chat (and
   * existing tests) do not need to pass it. */
  onTaskEvent?: (event: TaskEvent) => void;
}

export function ChatPanel({ sessionId, workspaceId, onDagEvent, onTaskEvent }: ChatPanelProps) {
  const { isLoading: authLoading, error: authError } = useAuth();
  const [query, setQuery] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isRunningTask, setIsRunningTask] = useState(false);
  const [forkState, setForkState] = useState<ForkState>({ status: "idle" });

  const replaceLastAgentMessage = (text: string) => {
    setMessages((prev) => {
      if (prev.length === 0) return prev;
      const updated = [...prev];
      const lastIndex = updated.length - 1;
      if (updated[lastIndex].role === "agent") {
        updated[lastIndex] = { ...updated[lastIndex], text };
      }
      return updated;
    });
  };

  const handleSend = async () => {
    if (!query.trim() || !sessionId) return;

    setMessages((prev) => [
      ...prev,
      { role: "user", text: query },
      { role: "agent", text: "Iniciando orquestração..." },
    ]);
    setQuery("");
    setIsStreaming(true);

    try {
      for await (const evt of streamChat(sessionId, query)) {
        replaceLastAgentMessage(evt.message);
        if (evt.event === "planning" || evt.event === "completed" || evt.event === "error") {
          onDagEvent(evt.event);
        }
      }
    } catch (err) {
      replaceLastAgentMessage(
        `Erro ao contatar o orquestrador: ${err instanceof Error ? err.message : "desconhecido"}`
      );
      onDagEvent("error");
    } finally {
      setIsStreaming(false);
    }
  };

  const handleFork = async () => {
    if (!workspaceId) return;
    setForkState({ status: "loading" });
    try {
      const childMountPath = `workspace_fork_${crypto.randomUUID()}`;
      const child = await forkWorkspace(workspaceId, childMountPath);
      setForkState({ status: "success", path: child.fs_mount_path });
    } catch (err) {
      setForkState({
        status: "error",
        message: err instanceof Error ? err.message : "Fork failed.",
      });
    }
  };

  const handleSubmitTask = async () => {
    if (!query.trim() || !sessionId) return;

    const task = query;
    setQuery("");
    setIsRunningTask(true);
    try {
      for await (const evt of streamTask(sessionId, task)) {
        onTaskEvent?.(evt);
      }
    } catch (err) {
      onTaskEvent?.({
        event: "error",
        message: err instanceof Error ? err.message : "Task execution failed.",
      });
    } finally {
      setIsRunningTask(false);
    }
  };

  const sendDisabled = isStreaming || isRunningTask || authLoading || !sessionId;
  const taskDisabled = isStreaming || isRunningTask || authLoading || !sessionId;
  const forkDisabled = forkState.status === "loading" || !workspaceId;

  return (
    <div
      data-testid="chat-panel"
      className="w-1/4 h-full border-r border-[#1a1a24] bg-[#0c0c0e] flex flex-col justify-between p-4"
    >
      <div className="flex flex-col flex-1 overflow-y-auto space-y-4">
        <Header />

        {authError && (
          <p data-testid="auth-error" className="text-xs text-[#ff8686]">
            {authError}
          </p>
        )}

        <div className="flex-1 space-y-3 py-2">
          {messages.length === 0 ? (
            <p className="text-sm text-[#707086] text-center pt-8">
              Nenhuma mensagem. Faça uma pergunta para iniciar o orquestrador MCTS.
            </p>
          ) : (
            messages.map((m, idx) => (
              <div
                key={idx}
                className={`p-3 rounded-lg text-sm ${
                  m.role === "user" ? "bg-[#181822] text-[#fff]" : "bg-[#0f2a24] text-[#86ffcf]"
                }`}
              >
                <span className="block text-[10px] font-bold uppercase tracking-wider text-[#a0a0b8] mb-1">
                  {m.role === "user" ? "Você" : "Orquestrador OSW"}
                </span>
                <p className="leading-relaxed">{m.text}</p>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="mt-4 space-y-2">
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Digite sua query cientifica..."
          className="w-full h-24 bg-[#141416] border border-[#242435] rounded-lg p-2 text-sm text-white focus:outline-none focus:border-[#404060]"
        />
        <div className="flex gap-2">
          <button
            onClick={handleSend}
            disabled={sendDisabled}
            className="flex-1 bg-[#2e624d] hover:bg-[#3d7a62] text-white py-2 rounded-lg text-sm font-semibold transition-all disabled:opacity-50"
          >
            {isStreaming ? "Processando..." : "Enviar"}
          </button>
          <button
            onClick={handleFork}
            disabled={forkDisabled}
            className="px-4 py-2 border border-[#242435] hover:bg-[#181822] rounded-lg text-sm font-semibold text-white transition-all disabled:opacity-50"
          >
            {forkState.status === "loading" ? "Bifurcando..." : "Fork"}
          </button>
        </div>
        <button
          onClick={handleSubmitTask}
          disabled={taskDisabled}
          className="w-full border border-[#404060] hover:bg-[#181822] text-[#a0a0b8] hover:text-white py-2 rounded-lg text-sm font-semibold transition-all disabled:opacity-50"
        >
          {isRunningTask ? "Executando MCTS..." : "Executar Tarefa (MCTS)"}
        </button>
        {forkState.status === "success" && (
          <p data-testid="fork-success" className="text-xs text-[#86ffcf]">
            Fork criado: {forkState.path}
          </p>
        )}
        {forkState.status === "error" && (
          <p data-testid="fork-error" className="text-xs text-[#ff8686]">
            {forkState.message}
          </p>
        )}
      </div>
    </div>
  );
}
