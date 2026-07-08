"use client";

import { useMemo } from "react";
import { Background, Controls, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { DAGNode } from "./types";

const STATUS_STYLES: Record<DAGNode["status"], { bg: string; border: string; text: string }> = {
  success: { bg: "#0f1f1a", border: "#225c48", text: "#86ffcf" },
  running: { bg: "#292212", border: "#7d6124", text: "#ffd175" },
  pending: { bg: "#121217", border: "#242435", text: "#707086" },
  failed: { bg: "#2a1010", border: "#7d2424", text: "#ff8686" },
};

/**
 * Assigns a simple depth-based (x, y) position to each node: depth 0 (no
 * `parentId`) at the top, each level below its parent's, siblings spread
 * horizontally. Deliberately minimal -- there is no real MCTS tree-search
 * backend yet (`SubmitTaskUseCase` does not produce real tree structure, see
 * `docs/planning/execution_plan_gap_closure.md`), so a linear/shallow-tree
 * layout is sufficient here rather than a full graph-layout algorithm.
 */
function computeLayout(nodes: DAGNode[]): Map<string, { x: number; y: number }> {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const depthCache = new Map<string, number>();

  function depthOf(id: string, guard: Set<string>): number {
    if (depthCache.has(id)) return depthCache.get(id)!;
    const node = byId.get(id);
    if (!node?.parentId || guard.has(id)) return 0;
    guard.add(id);
    const depth = depthOf(node.parentId, guard) + 1;
    depthCache.set(id, depth);
    return depth;
  }

  const countPerLevel = new Map<number, number>();
  const positions = new Map<string, { x: number; y: number }>();
  for (const node of nodes) {
    const depth = depthOf(node.id, new Set());
    const indexInLevel = countPerLevel.get(depth) ?? 0;
    countPerLevel.set(depth, indexInLevel + 1);
    positions.set(node.id, { x: indexInLevel * 220, y: depth * 140 });
  }
  return positions;
}

export interface MCTSGraphProps {
  dagNodes: DAGNode[];
}

export function MCTSGraph({ dagNodes }: MCTSGraphProps) {
  const { nodes, edges } = useMemo(() => {
    const positions = computeLayout(dagNodes);

    const nodes: Node[] = dagNodes.map((n) => {
      const style = STATUS_STYLES[n.status];
      return {
        id: n.id,
        position: positions.get(n.id) ?? { x: 0, y: 0 },
        data: {
          label: (
            <div className="text-left" data-testid={`mcts-node-${n.id}`}>
              <div className="flex items-center justify-between gap-2 mb-1">
                <span className="font-mono font-semibold text-[11px]">Node #{n.id}</span>
                <span
                  className="px-1.5 py-0.5 rounded text-[9px] uppercase font-bold"
                  style={{ background: style.border, color: "#fff" }}
                >
                  {n.status}
                </span>
              </div>
              <p className="font-mono text-[10px] leading-relaxed">{n.label}</p>
            </div>
          ),
        },
        style: {
          background: style.bg,
          border: `1px solid ${style.border}`,
          color: style.text,
          borderRadius: 8,
          padding: 8,
          width: 190,
        },
      };
    });

    const edges: Edge[] = dagNodes
      .filter((n): n is DAGNode & { parentId: string } => Boolean(n.parentId))
      .map((n) => ({
        id: `${n.parentId}-${n.id}`,
        source: n.parentId,
        target: n.id,
        animated: n.status === "running",
        style: { stroke: "#404060" },
      }));

    return { nodes, edges };
  }, [dagNodes]);

  return (
    <div data-testid="mcts-graph" className="flex-1 w-full min-h-[240px]">
      <ReactFlow nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }}>
        <Background color="#1a1a24" gap={16} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
