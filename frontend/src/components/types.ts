import type { BackendDAGNode } from "@/lib/api-client";

export interface Message {
  role: "user" | "agent";
  text: string;
}

/**
 * A textual correction raised by the Actor-Critic reviewer (RF-002/RF-008),
 * attached to a manuscript so the editor can apply it in place.
 */
export interface ManuscriptComment {
  id: string;
  /** Exact substring in the LaTeX source this comment targets. */
  targetText: string;
  /** Replacement text the critic suggests. */
  suggestion: string;
  resolved?: boolean;
}

/**
 * Job-derived data that drives the scientific viewers (RF-007). Populated from a
 * completed analysis result; when absent, each viewer falls back to its own demo
 * default (Molstar -> 1CRN, IGV -> hg38 MYC locus).
 */
export interface VisualizationResult {
  /** RCSB PDB id of a produced structure for Mol*. */
  pdbId?: string;
  /** Reference genome id for igv.js. */
  genome?: string;
  /** Genomic locus for igv.js. */
  locus?: string;
}

export interface DAGNode {
  id: string;
  label: string;
  status: "pending" | "running" | "success" | "failed";
  /**
   * Id of this node's parent in the MCTS search tree, if any. Root node(s)
   * omit this field. Used by `MCTSGraph` to derive React Flow edges and a
   * simple depth-based layout -- see `components/MCTSGraph.tsx`.
   */
  parentId?: string;
}

export const initialDagNodes: DAGNode[] = [
  { id: "1", label: "MCTS Root: Initialize", status: "success" },
  { id: "2", label: "MCTS Node A: Analyze FASTQ", status: "pending", parentId: "1" },
  { id: "3", label: "MCTS Node B: Predict folding", status: "pending", parentId: "1" },
];

/**
 * Maps one backend `DAGNode` (see `lib/api-client.ts`'s `BackendDAGNode`,
 * mirroring `backend/src/domain/entities/dag.py`) onto the frontend's
 * `DAGNode` shape consumed by `MCTSGraph`.
 *
 * The backend has no "running" node status (only PENDING/COMPLETED/PRUNED) --
 * that is a purely frontend concept, derived from a live `node_start` SSE
 * event rather than from `status` itself, so callers pass it explicitly via
 * `overrideStatus` when handling that event.
 *
 * Backend nodes carry a free-text `description`, not a `label` -- this
 * mapping is REQUIRED (not optional) so a mapped node is never shipped with
 * empty label text: `description` always backs `label`, falling back to the
 * node id only in the (should-never-happen) case of an empty description.
 */
export function mapBackendNode(
  node: BackendDAGNode,
  overrideStatus?: DAGNode["status"]
): DAGNode {
  const status: DAGNode["status"] =
    overrideStatus ??
    (node.status === "COMPLETED" ? "success" : node.status === "PRUNED" ? "failed" : "pending");

  return {
    id: node.id,
    label: node.description || `Node ${node.id}`,
    status,
    // MCTSGraph's layout only understands a single parent per node; the
    // backend DAG allows multiple dependencies, so the first one (if any) is
    // used to place this node under its primary prerequisite.
    parentId: node.dependencies[0],
  };
}
