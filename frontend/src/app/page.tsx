"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { createSession } from "@/lib/api-client";
import { useAuth } from "@/lib/auth";

import { ChatPanel } from "@/components/ChatPanel";
import { MCTSGraph } from "@/components/MCTSGraph";
import { VisualizerPanel } from "@/components/VisualizerPanel";
import { initialDagNodes, type DAGNode, type VisualizationResult } from "@/components/types";

const LOCAL_WORKSPACE_ID_KEY = "osw.workspaceId";

function getOrCreateLocalWorkspaceId(): string {
  if (typeof window === "undefined") return crypto.randomUUID();
  const existing = window.localStorage.getItem(LOCAL_WORKSPACE_ID_KEY);
  if (existing) return existing;
  const created = crypto.randomUUID();
  window.localStorage.setItem(LOCAL_WORKSPACE_ID_KEY, created);
  return created;
}

export default function Home() {
  const { userId, isLoading: authLoading, error: authError } = useAuth();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [dagNodes, setDagNodes] = useState<DAGNode[]>(initialDagNodes);
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

  const handleDagEvent = useCallback((event: "planning" | "completed" | "error") => {
    setDagNodes((nodes) => {
      if (event === "planning") {
        return nodes.map((n) => (n.id === "2" ? { ...n, status: "running" } : n));
      }
      if (event === "completed") {
        return nodes.map((n) =>
          n.id === "2" || n.id === "3" ? { ...n, status: "success" } : n
        );
      }
      // 'error': any node currently mid-flight failed.
      return nodes.map((n) => (n.status === "running" ? { ...n, status: "failed" } : n));
    });
  }, []);

  return (
    <div className="flex h-screen w-screen bg-[#0a0a0c] text-[#ededf0] overflow-hidden font-sans">
      {/* Panel 1: Chat Window (Left Panel) */}
      <ChatPanel sessionId={sessionId} workspaceId={workspaceId} onDagEvent={handleDagEvent} />

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
        <MCTSGraph dagNodes={dagNodes} />
      </div>
    </div>
  );
}
