import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MCTSGraph } from "./MCTSGraph";
import { initialDagNodes, type DAGNode } from "./types";

describe("MCTSGraph", () => {
  it("renders the graph container and one React Flow node per DAG node", () => {
    render(<MCTSGraph dagNodes={initialDagNodes} />);

    expect(screen.getByTestId("mcts-graph")).toBeInTheDocument();
    for (const node of initialDagNodes) {
      expect(screen.getByTestId(`mcts-node-${node.id}`)).toBeInTheDocument();
      expect(screen.getByText(node.label)).toBeInTheDocument();
    }
  });

  it("reflects each node's status label", () => {
    const nodes: DAGNode[] = [
      { id: "1", label: "Root", status: "success" },
      { id: "2", label: "Child running", status: "running", parentId: "1" },
    ];

    render(<MCTSGraph dagNodes={nodes} />);

    expect(screen.getByTestId("mcts-node-1")).toHaveTextContent("success");
    expect(screen.getByTestId("mcts-node-2")).toHaveTextContent("running");
  });

  it("renders an empty graph without crashing when there are no nodes", () => {
    render(<MCTSGraph dagNodes={[]} />);
    expect(screen.getByTestId("mcts-graph")).toBeInTheDocument();
  });
});
