"""RNF-008: VRAM admission-check logic (`Evo2ScalingDecision`) and its use in
`DispatchHPCJobUseCase`.

Modal/cloud-GPU dispatch has been removed entirely (this project's locked
architecture is a single local Linux server, no external cluster) --
`Evo2ScalingDecision` no longer chooses a remote dispatch target, it only
reports whether a job's declared VRAM need fits locally. `DispatchHPCJobUseCase`
no longer accepts (or needs) a `modal_dispatcher` argument: there is exactly
one configured `HPCJobDispatcherPort` per deployment, and every job goes to
it regardless of the VRAM admission outcome, unless
`reject_if_insufficient_vram=True` is set.
"""
import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

from src.domain.entities.agent_session import AgentSession
from src.domain.services.evo2_scaling_decision import Evo2ScalingDecision, VRAMAdmissionDecision
from src.application.use_cases.dispatch_hpc_job import DispatchHPCJobUseCase
from tests.unit.test_create_session import MockSessionRepository


class RecordingDispatcher:
    def __init__(self, job_id):
        self.job_id = job_id
        self.calls = 0

    async def dispatch(self, sbatch_script: str) -> str:
        self.calls += 1
        return self.job_id


def test_evaluate_reports_insufficient_when_required_exceeds_available():
    decision = Evo2ScalingDecision().evaluate(required_vram_gb=48, local_vram_gb=24)
    assert decision == VRAMAdmissionDecision(fits=False, required_vram_gb=48, available_vram_gb=24)
    assert "exceeds" in decision.message
    assert "No remote GPU backend" in decision.message


def test_evaluate_reports_sufficient_when_required_fits():
    decision = Evo2ScalingDecision().evaluate(required_vram_gb=10, local_vram_gb=24)
    assert decision == VRAMAdmissionDecision(fits=True, required_vram_gb=10, available_vram_gb=24)
    assert "fits within" in decision.message


def test_evaluate_exact_match_fits():
    decision = Evo2ScalingDecision().evaluate(required_vram_gb=24, local_vram_gb=24)
    assert decision.fits is True


async def _run(required_vram_gb, local_vram_gb, reject_if_insufficient_vram=False):
    repo = MockSessionRepository()
    session = AgentSession(workspace_id=uuid4(), session_status="DAG_GENERATION")
    await repo.save(session)

    dispatcher = RecordingDispatcher("local_job_1")
    vram = MagicMock()
    vram.available_vram_gb = AsyncMock(return_value=local_vram_gb)

    use_case = DispatchHPCJobUseCase(
        session_repo=repo,
        dispatcher=dispatcher,
        vram_checker=vram,
        reject_if_insufficient_vram=reject_if_insufficient_vram,
    )
    job_id = await use_case.execute(
        session_id=session.id,
        job_name="evo2",
        script_payload="python evo2.py",
        required_vram_gb=required_vram_gb,
    )
    return job_id, dispatcher


@pytest.mark.asyncio
async def test_dispatch_still_runs_locally_and_warns_when_vram_insufficient(caplog):
    """No remote backend exists anymore -- an insufficient-VRAM job still
    dispatches to the single configured dispatcher, with a warning logged."""
    import logging

    with caplog.at_level(logging.WARNING, logger="src.application.use_cases.dispatch_hpc_job"):
        job_id, dispatcher = await _run(required_vram_gb=48, local_vram_gb=24)

    assert job_id == "local_job_1"
    assert dispatcher.calls == 1
    assert any("exceeds locally available VRAM" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_dispatch_runs_when_vram_sufficient():
    job_id, dispatcher = await _run(required_vram_gb=10, local_vram_gb=24)
    assert job_id == "local_job_1"
    assert dispatcher.calls == 1


@pytest.mark.asyncio
async def test_dispatch_rejected_when_insufficient_vram_and_strict_mode_enabled():
    with pytest.raises(ValueError, match="exceeds locally available VRAM"):
        await _run(required_vram_gb=48, local_vram_gb=24, reject_if_insufficient_vram=True)


@pytest.mark.asyncio
async def test_dispatch_skips_vram_check_when_not_requested():
    """`required_vram_gb=None` (the default) never even calls the VRAM checker."""
    repo = MockSessionRepository()
    session = AgentSession(workspace_id=uuid4(), session_status="DAG_GENERATION")
    await repo.save(session)

    dispatcher = RecordingDispatcher("local_job_2")
    vram = MagicMock()
    vram.available_vram_gb = AsyncMock(side_effect=AssertionError("should not be called"))

    use_case = DispatchHPCJobUseCase(session_repo=repo, dispatcher=dispatcher, vram_checker=vram)
    job_id = await use_case.execute(
        session_id=session.id, job_name="job", script_payload="echo hi"
    )

    assert job_id == "local_job_2"
    vram.available_vram_gb.assert_not_called()
