"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { createSession, type TaskEvent } from "@/lib/api-client";
import { useAuth } from "@/lib/auth";

import { ChatPanel } from "@/components/ChatPanel";
import { MCTSGraph } from "@/components/MCTSGraph";
import { VisualizerPanel } from "@/components/VisualizerPanel";
import { mapBackendNode, type DAGNode, type VisualizationResult } from "@/components/types";

const LOCAL_WORKSPACE_ID_KEY = "osw.workspaceId";

function getOrCreateLocalWorkspaceId(): string {
  if (typeof window === "undefined") return crypto.randomUUID();
  const existing = window.localStorage.getItem(LOCAL_WORKSPACE_ID_KEY);
  if (existing) return existing;
  const created = crypto.randomUUID();
  window.localStorage.setItem(LOCAL_WORKSPACE_ID_KEY, created);
  return created;
}

/**
 * UI state for the actor-critic review-status strip, driven entirely by real
 * "review" SSE events from `POST /api/v1/sessions/{session_id}/tasks` (see
 * `backend/src/application/use_cases/submit_task.py`'s `on_review` hook) --
 * this is the concrete, user-visible answer to "how does the bounded retry
 * loop surface to the user":
 *  - "approved": the critic accepted the DAG on this attempt.
 *  - "retrying": rejected, but under `max_review_attempts` -- the actor will
 *    re-plan and try again automatically.
 *  - "final-rejection": rejected on the last allowed attempt -- the loop has
 *    stopped and the session stays ARTIFACT_REJECTED.
 */
type ReviewStripState =
  | { status: "idle" }
  | { status: "approved" }
  | { status: "retrying"; attempt: number; maxAttempts: number; reason: string }
  | { status: "final-rejection"; attempt: number; maxAttempts: number; reason: string };

function ReviewStatusStrip({ state }: { state: ReviewStripState }) {
  if (state.status === "idle") return null;

  const stylesByStatus: Record<Exclude<ReviewStripState["status"], "idle">, string> = {
    approved: "bg-[#0f2a24] border-[#225c48] text-[#86ffcf]",
    retrying: "bg-[#292212] border-[#7d6124] text-[#ffd175]",
    "final-rejection": "bg-[#2a1010] border-[#7d2424] text-[#ff8686]",
  };

  const message =
    state.status === "approved"
      ? "Aprovado pelo crítico."
      : state.status === "retrying"
        ? `Rejeitado pelo crítico -- tentando novamente (tentativa ${state.attempt}/${state.maxAttempts}): ${state.reason}`
        : `Rejeição final após ${state.attempt}/${state.maxAttempts} tentativas: ${state.reason}`;

  return (
    <p
      data-testid="review-status-strip"
      data-status={state.status}
      className={`text-[11px] leading-relaxed rounded-lg border px-2 py-1.5 mb-2 ${stylesByStatus[state.status]}`}
    >
      {message}
    </p>
  );
}

export default function Home() {
  const { userId, isLoading: authLoading, error: authError } = useAuth();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  // Real, event-driven DAG state (RF-001/RF-002): starts empty and is
  // populated exclusively by `dag_planned`/`node_start`/`node_update` events
  // from a live `POST /api/v1/sessions/{session_id}/tasks` run -- no more
  // hardcoded demo nodes.
  const [dagNodes, setDagNodes] = useState<DAGNode[]>([]);
  const [reviewStrip, setReviewStrip] = useState<ReviewStripState>({ status: "idle" });
  const [taskError, setTaskError] = useState<string | null>(null);
  // Job-derived visualization data (RF-007); undefined until an analysis result
  // arrives, at which point the viewers render it instead of their demo default.
  const [visualization] = useState<VisualizationResult | undefined>(undefined);

  // Guards against React StrictMode's intentional double-invoke of effects in
  // development, which would otherwise provision two sessions for one page
  // load.
  const sessionRequested = useRef(false);

  useEffect(() => {
    if (authLoading || authError || !userId) return;
    if (sessionRequested.current) return;
    sessionRequested.current = true;

    const localWorkspaceId = getOrCreateLocalWorkspaceId();
    createSession(userId, localWorkspaceId)
      .then((session) => {
        setSessionId(session.id);
        setWorkspaceId(session.workspace_id);
      })
      .catch((err) => {
        setSessionError(err instanceof Error ? err.message : "Failed to create session.");
      });
  }, [authLoading, authError, userId]);

  // The plain conversational chat stream (`POST /sessions/{id}/chat`) carries
  // no real DAG data of its own -- real node/review state now comes
  // exclusively from `handleTaskEvent` below. Kept as a required `ChatPanel`
  // prop (see its own tests) but intentionally a no-op here.
  const handleDagEvent = useCallback(() => {}, []);

  const handleTaskEvent = useCallback((event: TaskEvent) => {
    switch (event.event) {
      case "dag_planned": {
        setDagNodes(event.nodes.map((n) => mapBackendNode(n)));
        setReviewStrip({ status: "idle" });
        setTaskError(null);
        break;
      }
      case "node_start": {
        setDagNodes((prev) =>
          prev.map((n) => (n.id === event.node.id ? mapBackendNode(event.node, "running") : n))
        );
        break;
      }
      case "node_update": {
        setDagNodes((prev) =>
          prev.map((n) => (n.id === event.node.id ? mapBackendNode(event.node) : n))
        );
        break;
      }
      case "review": {
        if (event.approved) {
          setReviewStrip({ status: "approved" });
        } else if (event.attempt >= event.max_attempts) {
          setReviewStrip({
            status: "final-rejection",
            attempt: event.attempt,
            maxAttempts: event.max_attempts,
            reason: event.reason,
          });
        } else {
          setReviewStrip({
            status: "retrying",
            attempt: event.attempt,
            maxAttempts: event.max_attempts,
            reason: event.reason,
          });
        }
        break;
      }
      case "error": {
        setTaskError(event.message);
        break;
      }
      case "completed":
        // Terminal marker only -- the review strip already reflects the final
        // approved/rejected state from the last "review" event.
        break;
    }
  }, []);

  return (
    <div className="flex h-screen w-screen bg-[#0a0a0c] text-[#ededf0] overflow-hidden font-sans">
      {/* Panel 1: Chat Window (Left Panel) */}
      <ChatPanel
        sessionId={sessionId}
        workspaceId={workspaceId}
        onDagEvent={handleDagEvent}
        onTaskEvent={handleTaskEvent}
      />

      {/* Panel 2: Scientific Visualizer Container (Center Panel) */}
      <VisualizerPanel result={visualization} />

      {/* Panel 3: MCTS Execution DAG tree (Right Panel) */}
      <div
        data-testid="dag-panel"
        className="w-1/5 h-full border-l border-[#1a1a24] bg-[#0c0c0e] p-4 flex flex-col"
      >
        <h2 className="text-sm font-bold tracking-wider text-[#a0a0b8] uppercase mb-4 pb-2 border-b border-[#1a1a24]">
          MCTS Search Tree
        </h2>
        {sessionError && (
          <p data-testid="session-error" className="text-xs text-[#ff8686] mb-2">
            {sessionError}
          </p>
        )}
        <ReviewStatusStrip state={reviewStrip} />
        {taskError && (
          <p data-testid="task-error" className="text-xs text-[#ff8686] mb-2">
            {taskError}
          </p>
        )}
        {dagNodes.length === 0 && (
          <p className="text-xs text-[#707086] text-center pt-8">
            Nenhuma tarefa em execução. Use &quot;Executar Tarefa (MCTS)&quot; para iniciar uma busca.
          </p>
        )}
        <MCTSGraph dagNodes={dagNodes} />
      </div>
    </div>
  );
}
