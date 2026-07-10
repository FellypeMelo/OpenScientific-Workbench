"""RNF-008: VRAM-threshold scale-out decision + Modal routing in the HPC
dispatch use case."""
import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

from src.domain.entities.agent_session import AgentSession
from src.domain.services.evo2_scaling_decision import Evo2ScalingDecision
from src.application.use_cases.dispatch_hpc_job import DispatchHPCJobUseCase
from tests.unit.test_create_session import MockSessionRepository


class RecordingDispatcher:
    def __init__(self, job_id):
        self.job_id = job_id
        self.calls = 0

    async def dispatch(self, sbatch_script: str) -> str:
        self.calls += 1
        return self.job_id


def test_select_remote_when_local_vram_insufficient():
    assert Evo2ScalingDecision().select_target(48, 24) == "remote_modal"


def test_select_local_when_local_vram_sufficient():
    assert Evo2ScalingDecision().select_target(10, 24) == "local"


async def _run(required_vram_gb, local_vram_gb):
    repo = MockSessionRepository()
    session = AgentSession(workspace_id=uuid4(), session_status="DAG_GENERATION")
    await repo.save(session)

    slurm = RecordingDispatcher("slurm_job")
    modal = RecordingDispatcher("modal_mock_job")
    vram = MagicMock()
    vram.available_vram_gb = AsyncMock(return_value=local_vram_gb)

    use_case = DispatchHPCJobUseCase(
        session_repo=repo, dispatcher=slurm, modal_dispatcher=modal, vram_checker=vram
    )
    job_id = await use_case.execute(
        session_id=session.id,
        job_name="evo2",
        script_payload="python evo2.py",
        required_vram_gb=required_vram_gb,
    )
    return job_id, slurm, modal


@pytest.mark.asyncio
async def test_dispatch_routes_to_modal_when_vram_insufficient():
    job_id, slurm, modal = await _run(required_vram_gb=48, local_vram_gb=24)
    assert job_id == "modal_mock_job"
    assert modal.calls == 1 and slurm.calls == 0


@pytest.mark.asyncio
async def test_dispatch_routes_to_slurm_when_vram_sufficient():
    job_id, slurm, modal = await _run(required_vram_gb=10, local_vram_gb=24)
    assert job_id == "slurm_job"
    assert slurm.calls == 1 and modal.calls == 0
