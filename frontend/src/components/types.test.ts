import { describe, expect, it } from "vitest";

import type { BackendDAGNode } from "@/lib/api-client";

import { mapBackendNode } from "./types";

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
