from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


class DAGNode(BaseModel):
    """A single sub-task node in the research plan produced by the orchestrator.

    ``reward`` stays ``None`` until the node is simulated; ``status`` moves
    PENDING -> COMPLETED (reward >= 0) or PENDING -> PRUNED (reward < 0, or an
    ancestor was pruned).
    """

    id: str
    description: str
    dependencies: List[str] = Field(default_factory=list)
    reward: Optional[float] = None
    status: str = "PENDING"


class DAGSnapshot(BaseModel):
    """Directed acyclic graph of sub-task nodes plus search bookkeeping.

    Serialisable to a plain dict (``to_dict``) for JSONB persistence on
    ``AgentSession.dag_snapshot`` -- it always carries ``nodes`` and ``edges``
    keys, replacing the old hardcoded ``{"completed": True, "task": ...}`` shape.
    """

    nodes: List[DAGNode] = Field(default_factory=list)
    edges: List[Tuple[str, str]] = Field(default_factory=list)
    tokens_spent: int = 0
    budget_exhausted: bool = False

    def get_node(self, node_id: str) -> Optional[DAGNode]:
        return next((n for n in self.nodes if n.id == node_id), None)

    def ready_nodes(self) -> List[DAGNode]:
        """PENDING nodes whose every dependency has COMPLETED (topological front)."""
        completed = {n.id for n in self.nodes if n.status == "COMPLETED"}
        return [
            n
            for n in self.nodes
            if n.status == "PENDING" and all(dep in completed for dep in n.dependencies)
        ]

    @property
    def is_complete(self) -> bool:
        """True once no node is still PENDING (all COMPLETED or PRUNED)."""
        return all(n.status != "PENDING" for n in self.nodes)

    @property
    def total_reward(self) -> float:
        return sum(n.reward for n in self.nodes if n.reward is not None)

    def to_dict(self) -> Dict[str, Any]:
        data = self.model_dump()
        # Expose the derived completion flag for convenience/back-compat.
        data["completed"] = self.is_complete
        return data
