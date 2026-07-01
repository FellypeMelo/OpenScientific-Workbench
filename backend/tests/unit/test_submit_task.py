import pytest
from uuid import uuid4
from src.domain.entities.agent_session import AgentSession
from tests.unit.test_create_session import MockSessionRepository
from src.application.use_cases.submit_task import SubmitTaskUseCase

@pytest.mark.asyncio
async def test_submit_task_success():
    session_repo = MockSessionRepository()
    session = AgentSession(workspace_id=uuid4())
    await session_repo.save(session)

    # Iniciar com budget de tokens suficiente
    use_case = SubmitTaskUseCase(session_repo=session_repo, default_token_limit=1000)
    
    updated_session = await use_case.execute(session_id=session.id, task_nl="Solve gene sequencing")
    assert updated_session.session_status == "SNAPSHOT_TAKEN"
    assert updated_session.dag_snapshot.get("completed") is True
    # Provenance log should be updated
    assert len(updated_session.provenance_log) > 0

@pytest.mark.asyncio
async def test_submit_task_budget_exceeded():
    session_repo = MockSessionRepository()
    session = AgentSession(workspace_id=uuid4())
    await session_repo.save(session)

    # budget zero
    use_case = SubmitTaskUseCase(session_repo=session_repo, default_token_limit=0)
    
    with pytest.raises(ValueError, match="FATAL_LLM_BUDGET_EXCEEDED"):
        await use_case.execute(session_id=session.id, task_nl="Solve gene sequencing")
