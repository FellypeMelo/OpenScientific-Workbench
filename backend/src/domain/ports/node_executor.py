from typing import Protocol

from src.domain.entities.dag import DAGNode


class NodeExecutorPort(Protocol):
    """Executes (simulates) a single DAG node and returns its reward.

    Reward convention: ``>= 0`` means the step succeeded (node COMPLETED),
    ``< 0`` means it failed (node PRUNED, mirroring the reward=-1 pruning in the
    MCTS activity diagram). The concrete implementation runs the node's work in
    the sandbox/HPC layer; tests inject a fake returning fixed rewards.
    """

    async def simulate(self, node: DAGNode) -> float:
        ...
