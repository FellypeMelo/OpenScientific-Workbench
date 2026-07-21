"""Unit tests for the MCTS-over-DAG orchestrator (RF-001).

Pure domain logic: the LLM planner and the node executor are injected as ports
and faked here, so the search/expand/reward/prune/budget behaviour is fully
deterministic and needs no external services.
"""
import pytest

from src.domain.entities.dag import DAGNode, DAGSnapshot
from src.domain.services.mcts_orchestrator import MCTSOrchestrator


class FakePlanner:
    """Returns a pre-built plan, records how many times it was asked to plan."""

    def __init__(self, snapshot: DAGSnapshot):
        self._snapshot = snapshot
        self.calls = 0

    async def plan(self, task_nl: str) -> DAGSnapshot:
        self.calls += 1
        # Return a deep copy so the orchestrator mutating nodes never leaks back.
        return self._snapshot.model_copy(deep=True)


class FakeExecutor:
    """Returns a fixed reward per node id; records simulated node ids in order."""

    def __init__(self, rewards: dict[str, float], default: float = 1.0):
        self._rewards = rewards
        self._default = default
        self.simulated: list[str] = []

    async def simulate(self, node: DAGNode) -> float:
        self.simulated.append(node.id)
        return self._rewards.get(node.id, self._default)


def _linear_plan() -> DAGSnapshot:
    return DAGSnapshot(
        nodes=[
            DAGNode(id="n1", description="load sequence data", dependencies=[]),
            DAGNode(id="n2", description="run alignment", dependencies=["n1"]),
        ],
        edges=[("n1", "n2")],
    )


@pytest.mark.asyncio
async def test_expand_returns_dag_with_multiple_unrewarded_nodes():
    orch = MCTSOrchestrator(planner=FakePlanner(_linear_plan()), executor=FakeExecutor({}))

    snapshot = await orch.expand("align these genes")

    assert isinstance(snapshot, DAGSnapshot)
    assert len(snapshot.nodes) >= 2
    for node in snapshot.nodes:
        assert node.id
        assert isinstance(node.dependencies, list)
        assert node.reward is None
        assert node.status == "PENDING"

    as_dict = snapshot.to_dict()
    assert "nodes" in as_dict and "edges" in as_dict
    assert len(as_dict["nodes"]) > 1
    # It must NOT be the old hardcoded {"completed": True, "task": ...} shape.
    assert as_dict.get("task") != "align these genes"


@pytest.mark.asyncio
async def test_run_simulates_ready_nodes_in_dependency_order():
    planner = FakePlanner(_linear_plan())
    executor = FakeExecutor({"n1": 1.0, "n2": 1.0})
    orch = MCTSOrchestrator(planner=planner, executor=executor, token_budget=1000, step_cost=100)

    result = await orch.run("task")

    # Dependency order respected: n1 simulated before n2.
    assert executor.simulated == ["n1", "n2"]
    assert result.get_node("n1").status == "COMPLETED"
    assert result.get_node("n2").status == "COMPLETED"
    assert result.get_node("n1").reward == 1.0
    assert result.is_complete is True
    assert result.tokens_spent == 200


@pytest.mark.asyncio
async def test_run_prunes_negative_reward_node_and_its_dependents():
    planner = FakePlanner(_linear_plan())
    executor = FakeExecutor({"n1": -1.0})  # n1 fails -> n2 depends on it
    orch = MCTSOrchestrator(planner=planner, executor=executor, token_budget=1000, step_cost=100)

    result = await orch.run("task")

    assert result.get_node("n1").status == "PRUNED"
    assert result.get_node("n1").reward == -1.0
    # n2 depended on the pruned n1 -> it must never be simulated, marked PRUNED.
    assert "n2" not in executor.simulated
    assert result.get_node("n2").status == "PRUNED"


@pytest.mark.asyncio
async def test_run_stops_when_token_budget_exhausted():
    planner = FakePlanner(_linear_plan())
    executor = FakeExecutor({"n1": 1.0, "n2": 1.0})
    # Budget only affords one simulation (step_cost=100, budget=150).
    orch = MCTSOrchestrator(planner=planner, executor=executor, token_budget=150, step_cost=100)

    result = await orch.run("task")

    assert executor.simulated == ["n1"]
    assert result.budget_exhausted is True
    assert result.is_complete is False
    assert result.get_node("n2").status == "PENDING"


@pytest.mark.asyncio
async def test_run_fires_progress_hooks_in_order_when_provided():
    """Optional progress hooks (on_plan/on_node_start/on_node_update) are
    additive: they default to None (see the other tests above, which pass none
    of them and still work unmodified), and when provided are called
    synchronously at the natural points in run()."""
    planner = FakePlanner(_linear_plan())
    executor = FakeExecutor({"n1": 1.0, "n2": 1.0})
    events: list[tuple] = []

    orch = MCTSOrchestrator(
        planner=planner,
        executor=executor,
        token_budget=1000,
        step_cost=100,
        on_plan=lambda snapshot: events.append(("plan", len(snapshot.nodes))),
        on_node_start=lambda node: events.append(("start", node.id)),
        on_node_update=lambda node: events.append(("update", node.id, node.status)),
    )

    await orch.run("task")

    assert events == [
        ("plan", 2),
        ("start", "n1"),
        ("update", "n1", "COMPLETED"),
        ("start", "n2"),
        ("update", "n2", "COMPLETED"),
    ]


@pytest.mark.asyncio
async def test_run_fires_node_update_hook_with_pruned_status():
    planner = FakePlanner(_linear_plan())
    executor = FakeExecutor({"n1": -1.0})
    updates: list[str] = []

    orch = MCTSOrchestrator(
        planner=planner,
        executor=executor,
        token_budget=1000,
        step_cost=100,
        on_node_update=lambda node: updates.append(node.status),
    )

    await orch.run("task")

    # n2 is pruned by propagation, never simulated -> never fires on_node_update
    # for it (only n1, the one that was actually simulated, does).
    assert updates == ["PRUNED"]
