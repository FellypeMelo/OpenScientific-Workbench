export interface Message {
  role: "user" | "agent";
  text: string;
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
