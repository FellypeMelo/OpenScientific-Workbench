import { describe, expect, it } from "vitest";

import type { BackendCriticComment, BackendDAGNode } from "@/lib/api-client";

import { extractVisualization, mapBackendComment, mapBackendNode } from "./types";

function backendNode(overrides: Partial<BackendDAGNode> = {}): BackendDAGNode {
  return {
    id: "n1",
    description: "Align reads to reference genome",
    dependencies: [],
    reward: null,
    status: "PENDING",
    output: null,
    expected: null,
    ...overrides,
  };
}

describe("mapBackendNode", () => {
  it("maps the backend description onto the frontend label field", () => {
    const node = mapBackendNode(backendNode({ description: "Run alignment" }));
    expect(node.label).toBe("Run alignment");
  });

  it("never ships a node with empty label text, even for an empty description", () => {
    const node = mapBackendNode(backendNode({ id: "n7", description: "" }));
    expect(node.label.trim().length).toBeGreaterThan(0);
  });

  it.each([
    ["PENDING", "pending"],
    ["COMPLETED", "success"],
    ["PRUNED", "failed"],
  ] as const)("maps backend status %s to frontend status %s", (backendStatus, frontendStatus) => {
    const node = mapBackendNode(backendNode({ status: backendStatus }));
    expect(node.status).toBe(frontendStatus);
  });

  it("lets an explicit overrideStatus win over the backend status (e.g. a live node_start event)", () => {
    const node = mapBackendNode(backendNode({ status: "PENDING" }), "running");
    expect(node.status).toBe("running");
  });

  it("derives parentId from the first dependency, when present", () => {
    const node = mapBackendNode(backendNode({ dependencies: ["n1", "n2"] }));
    expect(node.parentId).toBe("n1");
  });

  it("leaves parentId undefined for a root node with no dependencies", () => {
    const node = mapBackendNode(backendNode({ dependencies: [] }));
    expect(node.parentId).toBeUndefined();
  });

  it("carries the node id through unchanged", () => {
    const node = mapBackendNode(backendNode({ id: "n42" }));
    expect(node.id).toBe("n42");
  });
});

describe("mapBackendComment", () => {
  function backendComment(overrides: Partial<BackendCriticComment> = {}): BackendCriticComment {
    return { id: "c1", target_text: "afinity", suggestion: "affinity", resolved: false, ...overrides };
  }

  it("maps snake_case backend fields onto the frontend's camelCase shape", () => {
    const comment = mapBackendComment(backendComment());
    expect(comment).toEqual({
      id: "c1",
      targetText: "afinity",
      suggestion: "affinity",
      resolved: false,
    });
  });

  it("carries a resolved=true comment through unchanged", () => {
    const comment = mapBackendComment(backendComment({ resolved: true }));
    expect(comment.resolved).toBe(true);
  });
});

describe("extractVisualization (RF-007)", () => {
  function backendNode(overrides: Partial<BackendDAGNode> = {}): BackendDAGNode {
    return {
      id: "n1",
      description: "fetch structure",
      dependencies: [],
      reward: 1,
      status: "COMPLETED",
      ...overrides,
    };
  }

  it("returns undefined when the node has no output", () => {
    expect(extractVisualization(backendNode({ output: null }))).toBeUndefined();
  });

  it("returns undefined for a plain sandbox stdout with no recognizable JSON", () => {
    const node = backendNode({ output: { stdout: "Alignment complete.\n", exit_code: 0 } });
    expect(extractVisualization(node)).toBeUndefined();
  });

  it("extracts a pdbId from JSON a sandboxed script printed to stdout", () => {
    const node = backendNode({
      output: { stdout: '{"pdb_id": "1CRN"}\n', exit_code: 0 },
    });
    expect(extractVisualization(node)).toEqual({ pdbId: "1CRN", genome: undefined, locus: undefined });
  });

  it("extracts genome/locus from JSON on stdout", () => {
    const node = backendNode({
      output: { stdout: '{"genome": "hg38", "locus": "chr8:127,735,434-127,742,951"}', exit_code: 0 },
    });
    expect(extractVisualization(node)).toEqual({
      pdbId: undefined,
      genome: "hg38",
      locus: "chr8:127,735,434-127,742,951",
    });
  });

  it("ignores stdout JSON with no recognized visualization keys", () => {
    const node = backendNode({ output: { stdout: '{"exit_status": "ok"}', exit_code: 0 } });
    expect(extractVisualization(node)).toBeUndefined();
  });

  it("prefers fields set directly on output over parsing stdout", () => {
    const node = backendNode({ output: { pdb_id: "6XYZ", stdout: "irrelevant" } });
    expect(extractVisualization(node)?.pdbId).toBe("6XYZ");
  });

  it("returns undefined for the LLM node executor's {text: ...} shape", () => {
    const node = backendNode({ output: { text: "I fetched PDB structure 1CRN for you." } });
    expect(extractVisualization(node)).toBeUndefined();
  });

  it("does not throw on malformed stdout JSON", () => {
    const node = backendNode({ output: { stdout: "{not valid json", exit_code: 0 } });
    expect(extractVisualization(node)).toBeUndefined();
  });
});
