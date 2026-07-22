from typing import Callable, Optional

from src.domain.entities.dag import DAGNode, DAGSnapshot
from src.domain.ports.node_executor import NodeExecutorPort
from src.domain.ports.task_planner import TaskPlannerPort


class MCTSOrchestrator:
    """Coordinates a research task as a search over a DAG of sub-tasks (RF-001).

    The flow follows the MCTS activity diagram, kept deliberately minimal
    (KISS/YAGNI) but faithful to its concepts:

    - **expansion**: the injected planner turns the NL task into a DAG of nodes;
    - **simulation**: each ready node (all dependencies COMPLETED) is run by the
      injected executor, which returns a reward;
    - **reward / pruning**: reward < 0 prunes the node and, by propagation, every
      node that (transitively) depends on it -- those branches are abandoned;
    - **budget**: each simulation costs ``step_cost`` tokens; the loop stops early
      once the remaining budget can no longer afford another step.

    Both collaborators are domain ports, so the whole search is deterministic and
    infrastructure-free under test.

    Optional progress hooks (``on_plan``/``on_node_start``/``on_node_update``) let
    a live caller (e.g. an SSE route) observe the search as it happens without the
    orchestrator itself knowing anything about HTTP/streaming. All three default
    to ``None`` (no-op) so existing callers/tests are unaffected; when set, each
    is called synchronously (plain callables, not awaited) at the natural point
    in ``run()`` -- a callback that needs to reach an async context (e.g. push
    onto an ``asyncio.Queue``) should use ``Queue.put_nowait`` rather than a
    coroutine.
    """

    def __init__(
        self,
        planner: TaskPlannerPort,
        executor: NodeExecutorPort,
        token_budget: int = 100_000,
        step_cost: int = 1_000,
        on_plan: Optional[Callable[[DAGSnapshot], None]] = None,
        on_node_start: Optional[Callable[[DAGNode], None]] = None,
        on_node_update: Optional[Callable[[DAGNode], None]] = None,
    ):
        self.planner = planner
        self.executor = executor
        self.token_budget = token_budget
        self.step_cost = step_cost
        self.on_plan = on_plan
        self.on_node_start = on_node_start
        self.on_node_update = on_node_update

    async def expand(self, task_nl: str) -> DAGSnapshot:
        """Expansion step: NL task -> DAG of PENDING sub-task nodes."""
        return await self.planner.plan(task_nl)

    async def run(self, task_nl: str) -> DAGSnapshot:
        """Expand then search: simulate ready nodes, reward, prune, until the DAG
        is resolved or the token budget is exhausted."""
        snapshot = await self.expand(task_nl)
        if self.on_plan:
            self.on_plan(snapshot)
        remaining = self.token_budget

        while True:
            ready = snapshot.ready_nodes()
            if not ready:
                break
            if remaining < self.step_cost:
                snapshot.budget_exhausted = True
                break

            node = ready[0]
            if self.on_node_start:
                self.on_node_start(node)
            reward = await self.executor.simulate(node)
            remaining -= self.step_cost
            node.reward = reward

            if reward < 0:
                node.status = "PRUNED"
                self._prune_dependents(snapshot, node.id)
            else:
                node.status = "COMPLETED"

            if self.on_node_update:
                self.on_node_update(node)

        snapshot.tokens_spent = self.token_budget - remaining
        return snapshot

    @staticmethod
    def _prune_dependents(snapshot: DAGSnapshot, pruned_id: str) -> None:
        """Backpropagate a failure: mark every node that still depends on a pruned
        node as PRUNED too (a branch whose prerequisite failed cannot run)."""
        frontier = [pruned_id]
        while frontier:
            current = frontier.pop()
            for node in snapshot.nodes:
                if node.status == "PENDING" and current in node.dependencies:
                    node.status = "PRUNED"
                    frontier.append(node.id)
