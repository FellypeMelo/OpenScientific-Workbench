from typing import Dict, Optional
from uuid import UUID, uuid4

import pytest

from src.domain.entities.agent_session import AgentSession
from src.domain.entities.dag import DAGNode, DAGSnapshot
from src.domain.entities.review import ReviewVerdict
from src.domain.entities.scientific_artifact import ScientificArtifact
from src.domain.ports.artifact_repository import ArtifactRepositoryPort
from src.domain.services.reproducibility import compute_lockfile_hash, default_lockfile_path
from tests.unit.test_create_session import MockSessionRepository
from src.application.use_cases.submit_task import SubmitTaskUseCase


class MockArtifactRepository(ArtifactRepositoryPort):
    """In-memory stand-in for `ArtifactRepositoryPort`, same style as
    `MockSessionRepository` in `tests/unit/test_create_session.py`."""

    def __init__(self):
        self.artifacts: Dict[str, ScientificArtifact] = {}

    async def get_by_id(self, artifact_id: UUID) -> Optional[ScientificArtifact]:
        return self.artifacts.get(str(artifact_id))

    async def save(self, artifact: ScientificArtifact) -> None:
        self.artifacts[str(artifact.id)] = artifact


class FakeOrchestrator:
    """Stands in for MCTSOrchestrator; returns a fixed resolved DAG."""

    def __init__(self, snapshot: DAGSnapshot):
        self._snapshot = snapshot
        self.ran_with = None
        self.run_count = 0

    async def run(self, task_nl: str) -> DAGSnapshot:
        self.ran_with = task_nl
        self.run_count += 1
        return self._snapshot.model_copy(deep=True)


class RejectingReviewer:
    """Always rejects, to drive the bounded actor-critic retry loop."""

    def __init__(self):
        self.calls = 0

    async def review(self, snapshot) -> ReviewVerdict:
        self.calls += 1
        return ReviewVerdict(approved=False, reason="numeric divergence at node n1")


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
async def test_submit_task_critic_rejection_retries_then_caps():
    session_repo = MockSessionRepository()
    session = AgentSession(workspace_id=uuid4())
    await session_repo.save(session)

    orchestrator = FakeOrchestrator(_resolved_snapshot())
    reviewer = RejectingReviewer()
    use_case = SubmitTaskUseCase(
        session_repo=session_repo,
        orchestrator=orchestrator,
        reviewer=reviewer,
        default_token_limit=1000,
        max_review_attempts=2,
    )

    updated = await use_case.execute(session_id=session.id, task_nl="dock ligand")

    # The actor re-planned once per rejected attempt, capped at max_review_attempts.
    assert updated.dag_generation_attempts == 2
    assert orchestrator.run_count == 2
    assert reviewer.calls == 2
    rejections = [e for e in updated.provenance_log if e.get("action") == "critic_rejected"]
    assert len(rejections) == 2
    assert updated.session_status == "ARTIFACT_REJECTED"


@pytest.mark.asyncio
async def test_submit_task_fires_on_review_hook_with_verdict_attempt_and_cap():
    session_repo = MockSessionRepository()
    session = AgentSession(workspace_id=uuid4())
    await session_repo.save(session)

    calls = []
    use_case = SubmitTaskUseCase(
        session_repo=session_repo,
        orchestrator=FakeOrchestrator(_resolved_snapshot()),
        default_token_limit=1000,
        on_review=lambda verdict, attempt, max_attempts: calls.append(
            (verdict.approved, attempt, max_attempts)
        ),
    )

    await use_case.execute(session_id=session.id, task_nl="Solve gene sequencing")

    assert calls == [(True, 1, 3)]


@pytest.mark.asyncio
async def test_submit_task_on_review_hook_fires_once_per_rejected_attempt():
    session_repo = MockSessionRepository()
    session = AgentSession(workspace_id=uuid4())
    await session_repo.save(session)

    calls = []
    use_case = SubmitTaskUseCase(
        session_repo=session_repo,
        orchestrator=FakeOrchestrator(_resolved_snapshot()),
        reviewer=RejectingReviewer(),
        default_token_limit=1000,
        max_review_attempts=2,
        on_review=lambda verdict, attempt, max_attempts: calls.append(
            (verdict.approved, attempt, max_attempts)
        ),
    )

    await use_case.execute(session_id=session.id, task_nl="dock ligand")

    # Final call (attempt == max_attempts, not approved) is the "final
    # rejection" a live caller (e.g. the SSE task route) tells apart from an
    # earlier "still retrying" rejection.
    assert calls == [(False, 1, 2), (False, 2, 2)]


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


@pytest.mark.asyncio
async def test_submit_task_saves_scientific_artifact_on_approval_when_artifact_repo_provided():
    """RNF-006: an approved run stamps a `ScientificArtifact` -- hashed against
    this backend's OWN `uv.lock` (never a caller-supplied hash/path) -- and
    persists it via the injected `artifact_repo`, right after the DAG snapshot
    itself is saved."""
    session_repo = MockSessionRepository()
    session = AgentSession(workspace_id=uuid4())
    await session_repo.save(session)

    artifact_repo = MockArtifactRepository()
    use_case = SubmitTaskUseCase(
        session_repo=session_repo,
        orchestrator=FakeOrchestrator(_resolved_snapshot()),
        default_token_limit=1000,
        artifact_repo=artifact_repo,
    )

    updated = await use_case.execute(session_id=session.id, task_nl="Solve gene sequencing")

    assert len(artifact_repo.artifacts) == 1
    artifact = next(iter(artifact_repo.artifacts.values()))
    assert artifact.session_id == updated.id
    # `_resolved_snapshot()`'s single node is `n1`, COMPLETED.
    assert artifact.name == "n1_output.json"
    # The hash is derived from this backend's real `uv.lock`, not accepted as
    # an arbitrary string -- must match `compute_lockfile_hash` run directly
    # against the same `default_lockfile_path()` the use case itself resolves.
    assert artifact.sha256_hash == compute_lockfile_hash(default_lockfile_path())


@pytest.mark.asyncio
async def test_submit_task_no_artifact_saved_without_artifact_repo():
    """Backward-compatible default: omitting `artifact_repo` (as every
    pre-existing caller/test in this module does) must not raise -- it simply
    skips artifact persistence, mirroring `on_review`'s optional no-op shape."""
    session_repo = MockSessionRepository()
    session = AgentSession(workspace_id=uuid4())
    await session_repo.save(session)

    use_case = SubmitTaskUseCase(
        session_repo=session_repo,
        orchestrator=FakeOrchestrator(_resolved_snapshot()),
        default_token_limit=1000,
    )

    updated = await use_case.execute(session_id=session.id, task_nl="Solve gene sequencing")

    assert updated.session_status == "SNAPSHOT_TAKEN"


@pytest.mark.asyncio
async def test_submit_task_does_not_save_artifact_when_all_attempts_rejected():
    """A run that never gets approved (capped-out retries) must not produce a
    ScientificArtifact -- there is no real output to stamp."""
    session_repo = MockSessionRepository()
    session = AgentSession(workspace_id=uuid4())
    await session_repo.save(session)

    artifact_repo = MockArtifactRepository()
    use_case = SubmitTaskUseCase(
        session_repo=session_repo,
        orchestrator=FakeOrchestrator(_resolved_snapshot()),
        reviewer=RejectingReviewer(),
        default_token_limit=1000,
        max_review_attempts=2,
        artifact_repo=artifact_repo,
    )

    updated = await use_case.execute(session_id=session.id, task_nl="dock ligand")

    assert updated.session_status == "ARTIFACT_REJECTED"
    assert artifact_repo.artifacts == {}
