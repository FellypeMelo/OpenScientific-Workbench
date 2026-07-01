import pytest
from uuid import uuid4
from src.domain.entities.agent_session import AgentSession
from tests.unit.test_create_session import MockSessionRepository
from src.application.use_cases.audit_artifact import AuditArtifactUseCase

@pytest.mark.asyncio
async def test_audit_artifact_success():
    session_repo = MockSessionRepository()
    session = AgentSession(workspace_id=uuid4(), session_status="REVIEW_PENDING")
    await session_repo.save(session)

    use_case = AuditArtifactUseCase(session_repo=session_repo, tolerance=1e-5)
    
    # Generated data matches expected within tolerance
    gen_data = {"affinity_kd": -7.820001}
    exp_data = {"affinity_kd": -7.820000}
    
    result = await use_case.execute(session_id=session.id, generated_data=gen_data, expected_data=exp_data)
    assert result is True
    # Session status should remain REVIEW_PENDING or move forward. (Wait, in our flow, if successful, MCTS proceeds. We assert it doesn't fail).

@pytest.mark.asyncio
async def test_audit_artifact_divergence_fails():
    session_repo = MockSessionRepository()
    session = AgentSession(workspace_id=uuid4(), session_status="REVIEW_PENDING")
    await session_repo.save(session)

    use_case = AuditArtifactUseCase(session_repo=session_repo, tolerance=1e-5)
    
    # Divergence > 1e-5
    gen_data = {"affinity_kd": -1.2200}
    exp_data = {"affinity_kd": -7.8200}
    
    with pytest.raises(ValueError, match="ERR_NUMERIC_DIVERGENCE"):
        await use_case.execute(session_id=session.id, generated_data=gen_data, expected_data=exp_data)
        
    # Verify session transitioned to ARTIFACT_REJECTED
    updated = await session_repo.get_by_id(session.id)
    assert updated.session_status == "ARTIFACT_REJECTED"
