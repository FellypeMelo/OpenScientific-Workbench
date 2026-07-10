import pytest
from uuid import uuid4

from src.domain.entities.agent_session import AgentSession
from src.domain.entities.dag import DAGNode, DAGSnapshot
from tests.unit.test_create_session import MockSessionRepository
from src.application.use_cases.submit_task import SubmitTaskUseCase


class FakeOrchestrator:
    """Stands in for MCTSOrchestrator; returns a fixed resolved DAG."""

    def __init__(self, snapshot: DAGSnapshot):
        self._snapshot = snapshot
        self.ran_with = None

    async def run(self, task_nl: str) -> DAGSnapshot:
        self.ran_with = task_nl
        return self._snapshot


def _resolved_snapshot() -> DAGSnapshot:
    return DAGSnapshot(
        nodes=[DAGNode(id="n1", description="align", dependencies=[], status="COMPLETED", reward=1.0)],
        edges=[],
        tokens_spent=1000,
    )


@pytest.mark.asyncio
async def test_submit_task_runs_orchestrator_and_persists_dag():
    session_repo = MockSessionRepository()
    session = AgentSession(workspace_id=uuid4())
    await session_repo.save(session)

    orchestrator = FakeOrchestrator(_resolved_snapshot())
    use_case = SubmitTaskUseCase(
        session_repo=session_repo, orchestrator=orchestrator, default_token_limit=1000
    )

    updated = await use_case.execute(session_id=session.id, task_nl="Solve gene sequencing")

    assert orchestrator.ran_with == "Solve gene sequencing"
    assert updated.session_status == "SNAPSHOT_TAKEN"
    # Real DAG shape, not the old {"completed": True, "task": ...} echo.
    assert "nodes" in updated.dag_snapshot and "edges" in updated.dag_snapshot
    assert len(updated.dag_snapshot["nodes"]) >= 1
    assert updated.dag_snapshot["completed"] is True
    assert len(updated.provenance_log) > 0


@pytest.mark.asyncio
async def test_submit_task_sanitizes_pii_before_writing_provenance():
    session_repo = MockSessionRepository()
    session = AgentSession(workspace_id=uuid4())
    await session_repo.save(session)

    use_case = SubmitTaskUseCase(
        session_repo=session_repo,
        orchestrator=FakeOrchestrator(_resolved_snapshot()),
        default_token_limit=1000,
    )

    updated = await use_case.execute(
        session_id=session.id, task_nl="Analyze exome for CPF 123.456.789-00"
    )

    logged_task = updated.provenance_log[-1]["task"]
    assert "123.456.789-00" not in logged_task
    assert "[CPF_MASKED]" in logged_task


@pytest.mark.asyncio
async def test_submit_task_budget_exceeded_before_running_orchestrator():
    session_repo = MockSessionRepository()
    session = AgentSession(workspace_id=uuid4())
    await session_repo.save(session)

    orchestrator = FakeOrchestrator(_resolved_snapshot())
    use_case = SubmitTaskUseCase(
        session_repo=session_repo, orchestrator=orchestrator, default_token_limit=0
    )

    with pytest.raises(ValueError, match="FATAL_LLM_BUDGET_EXCEEDED"):
        await use_case.execute(session_id=session.id, task_nl="Solve gene sequencing")

    # The orchestrator must not run once the budget guard trips.
    assert orchestrator.ran_with is None
