"""RF-003: submit_task must persist a checkpoint per attempt, not only once."""
import pytest
from uuid import uuid4

from src.domain.entities.agent_session import AgentSession
from src.application.use_cases.submit_task import SubmitTaskUseCase
from tests.unit.test_create_session import MockSessionRepository
from tests.unit.test_submit_task import FakeOrchestrator, RejectingReviewer, _resolved_snapshot


class CountingSessionRepo(MockSessionRepository):
    def __init__(self):
        super().__init__()
        self.save_calls = 0

    async def save(self, session):
        self.save_calls += 1
        await super().save(session)


@pytest.mark.asyncio
async def test_each_rejected_attempt_is_checkpointed():
    repo = CountingSessionRepo()
    session = AgentSession(workspace_id=uuid4())
    await repo.save(session)
    baseline = repo.save_calls  # the initial save above

    use_case = SubmitTaskUseCase(
        session_repo=repo,
        orchestrator=FakeOrchestrator(_resolved_snapshot()),
        reviewer=RejectingReviewer(),
        default_token_limit=1000,
        max_review_attempts=3,
    )

    await use_case.execute(session_id=session.id, task_nl="dock")

    # One checkpoint save per rejected attempt.
    assert repo.save_calls - baseline == 3


@pytest.mark.asyncio
async def test_successful_run_persists_once():
    repo = CountingSessionRepo()
    session = AgentSession(workspace_id=uuid4())
    await repo.save(session)
    baseline = repo.save_calls

    use_case = SubmitTaskUseCase(
        session_repo=repo,
        orchestrator=FakeOrchestrator(_resolved_snapshot()),
        default_token_limit=1000,
    )

    await use_case.execute(session_id=session.id, task_nl="dock")

    assert repo.save_calls - baseline == 1
