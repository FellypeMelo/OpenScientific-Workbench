import pytest
from uuid import uuid4
from src.domain.entities.agent_session import AgentSession
from src.domain.ports.hpc_job_dispatcher import HPCJobDispatcherPort
from tests.unit.test_create_session import MockSessionRepository
from src.application.use_cases.dispatch_hpc_job import DispatchHPCJobUseCase

class MockHPCJobDispatcher(HPCJobDispatcherPort):
    def __init__(self):
        self.dispatched_scripts = []
    async def dispatch(self, sbatch_script: str) -> str:
        self.dispatched_scripts.append(sbatch_script)
        return "job_10492"

@pytest.mark.asyncio
async def test_dispatch_hpc_job_success():
    session_repo = MockSessionRepository()
    session = AgentSession(workspace_id=uuid4(), session_status="DAG_GENERATION")
    await session_repo.save(session)

    dispatcher = MockHPCJobDispatcher()
    use_case = DispatchHPCJobUseCase(session_repo=session_repo, dispatcher=dispatcher)

    job_id = await use_case.execute(
        session_id=session.id,
        job_name="boltz_predict",
        script_payload="python run_boltz.py --input data.fasta",
        time_limit="02:00:00"
    )

    assert job_id == "job_10492"
    
    # Verify sbatch script generation
    assert len(dispatcher.dispatched_scripts) == 1
    script = dispatcher.dispatched_scripts[0]
    assert "#SBATCH --job-name=boltz_predict" in script
    assert "#SBATCH --time=02:00:00" in script
    assert "python run_boltz.py --input data.fasta" in script

    # Verify session transitioned to EXECUTING_HPC
    updated = await session_repo.get_by_id(session.id)
    assert updated.session_status == "EXECUTING_HPC"
