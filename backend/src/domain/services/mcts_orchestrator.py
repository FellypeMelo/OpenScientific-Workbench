from src.domain.entities.dag import DAGSnapshot
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
    """

    def __init__(
        self,
        planner: TaskPlannerPort,
        executor: NodeExecutorPort,
        token_budget: int = 100_000,
        step_cost: int = 1_000,
    ):
        self.planner = planner
        self.executor = executor
        self.token_budget = token_budget
        self.step_cost = step_cost

    async def expand(self, task_nl: str) -> DAGSnapshot:
        """Expansion step: NL task -> DAG of PENDING sub-task nodes."""
        return await self.planner.plan(task_nl)

    async def run(self, task_nl: str) -> DAGSnapshot:
        """Expand then search: simulate ready nodes, reward, prune, until the DAG
        is resolved or the token budget is exhausted."""
        snapshot = await self.expand(task_nl)
        remaining = self.token_budget

        while True:
            ready = snapshot.ready_nodes()
            if not ready:
                break
            if remaining < self.step_cost:
                snapshot.budget_exhausted = True
                break

            node = ready[0]
            reward = await self.executor.simulate(node)
            remaining -= self.step_cost
            node.reward = reward

            if reward < 0:
                node.status = "PRUNED"
                self._prune_dependents(snapshot, node.id)
            else:
                node.status = "COMPLETED"

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
