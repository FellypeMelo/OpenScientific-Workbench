import type { BackendCriticComment, BackendDAGNode } from "@/lib/api-client";

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
 * Maps one backend `CriticComment` (see `lib/api-client.ts`'s
 * `BackendCriticComment`, mirroring `backend/src/domain/entities/manuscript.py`)
 * onto the frontend's `ManuscriptComment` shape consumed by `ManuscriptEditor`
 * -- the real replacement for the previous hardcoded `DEFAULT_COMMENTS` demo
 * array (RF-008).
 */
export function mapBackendComment(comment: BackendCriticComment): ManuscriptComment {
  return {
    id: comment.id,
    targetText: comment.target_text,
    suggestion: comment.suggestion,
    resolved: comment.resolved,
  };
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

function pickVisualizationFields(obj: Record<string, unknown>): VisualizationResult | undefined {
  const pdbId =
    typeof obj.pdb_id === "string" ? obj.pdb_id : typeof obj.pdbId === "string" ? obj.pdbId : undefined;
  const genome = typeof obj.genome === "string" ? obj.genome : undefined;
  const locus = typeof obj.locus === "string" ? obj.locus : undefined;
  return pdbId || genome || locus ? { pdbId, genome, locus } : undefined;
}

function parseJSONObject(text: string): Record<string, unknown> | undefined {
  try {
    const parsed: unknown = JSON.parse(text.trim());
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Best-effort extraction of job-derived `VisualizationResult` data (RF-007)
 * from one completed backend `DAGNode`'s real `output`.
 *
 * There are two live shapes `node.output` can actually carry today (see
 * `backend/src/infrastructure/sandbox/sandbox_node_executor.py` and
 * `backend/src/infrastructure/llm/llm_node_executor.py`):
 *   1. `{"stdout": "...", "exit_code": 0}` -- `SandboxNodeExecutor`'s real
 *      shape when `execution_mode: "sandbox"` (the route's default). A
 *      sandboxed script's ONLY channel back to the caller is its own stdout,
 *      so a research script that wants to report a structured result (e.g.
 *      "I fetched PDB structure 1CRN") has no way to do so other than
 *      printing JSON -- this mirrors the exact "best-effort JSON extraction
 *      from free-form text" convention the backend itself already uses for
 *      LLM responses (see `domain/services/json_extraction.py`), applied
 *      here to a script's stdout instead.
 *   2. `{"text": "..."}` -- `LLMNodeExecutor`'s shape (`execution_mode:
 *      "llm"`), the model's raw prose answer. Prose is not scanned for
 *      embedded JSON (no delimiting convention to anchor a best-effort parse
 *      the way an LLM's whole response is), so this path never yields a
 *      result today.
 * Neither the DAG planner nor either node executor is currently instructed to
 * emit `pdb_id`/`genome`/`locus` -- so in live traffic today this reliably
 * returns `undefined` until a future planner prompt/tool asks a sandboxed
 * script to print one. The plumbing is real and exercised by tests; it has no
 * live producer emitting matching data yet.
 */
export function extractVisualization(node: BackendDAGNode): VisualizationResult | undefined {
  const output = node.output;
  if (!output) return undefined;

  const direct = pickVisualizationFields(output);
  if (direct) return direct;

  const stdout = output.stdout;
  if (typeof stdout === "string" && stdout.trim()) {
    const parsed = parseJSONObject(stdout);
    if (parsed) return pickVisualizationFields(parsed);
  }

  return undefined;
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
