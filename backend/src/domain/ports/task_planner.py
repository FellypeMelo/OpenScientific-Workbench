from typing import Protocol

from src.domain.entities.dag import DAGSnapshot


class TaskPlannerPort(Protocol):
    """Expands a natural-language research task into a DAG of sub-tasks.

    The concrete implementation lives in the infrastructure layer (an LLM-backed
    planner); the domain orchestrator only depends on this interface, so it can
    be exercised with a deterministic fake in tests.
    """

    async def plan(self, task_nl: str) -> DAGSnapshot:
        """Return a fresh DAGSnapshot whose nodes are all PENDING (reward=None)."""
        ...
