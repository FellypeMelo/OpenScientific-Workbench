import logging
from uuid import UUID

from src.domain.ports.session_repository import SessionRepositoryPort
from src.domain.ports.hpc_job_dispatcher import HPCJobDispatcherPort
from src.domain.ports.vram_checker import VRAMCheckerPort
from src.domain.services.evo2_scaling_decision import Evo2ScalingDecision

logger = logging.getLogger(__name__)


class DispatchHPCJobUseCase:
    """
    Application use case for compiling and dispatching sbatch jobs.

    `dispatcher` is whichever `HPCJobDispatcherPort` adapter is configured for
    this deployment (`presentation/dependencies.py::get_hpc_dispatcher` picks
    `LocalJobDispatcher` or `SlurmSSHDispatcher` per `settings.HPC_BACKEND`) --
    there is no remote GPU backend to route to instead (Modal/cloud dispatch
    was removed entirely, see `domain/services/evo2_scaling_decision.py`).

    When a VRAM checker and `required_vram_gb` are supplied, VRAM sufficiency
    is only an ADMISSION check now (RNF-008): if the job's declared need
    exceeds what's locally available, it is either dispatched anyway with a
    logged warning (the default -- there is nowhere else for it to go), or
    the dispatch is rejected outright with a clear message, per
    `reject_if_insufficient_vram`.
    """
    def __init__(
        self,
        session_repo: SessionRepositoryPort,
        dispatcher: HPCJobDispatcherPort,
        vram_checker: VRAMCheckerPort = None,
        scaling_decision: Evo2ScalingDecision = None,
        reject_if_insufficient_vram: bool = False,
    ):
        self.session_repo = session_repo
        self.dispatcher = dispatcher
        self.vram_checker = vram_checker
        self.scaling_decision = scaling_decision or Evo2ScalingDecision()
        self.reject_if_insufficient_vram = reject_if_insufficient_vram

    async def execute(
        self,
        session_id: UUID,
        job_name: str,
        script_payload: str,
        time_limit: str = "01:00:00",
        required_vram_gb: float = None,
    ) -> str:
        session = await self.session_repo.get_by_id(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found.")

        # Transition session to EXECUTING_HPC
        session.transition_to("EXECUTING_HPC")

        # Compile Slurm script
        sbatch_script = (
            f"#!/bin/bash\n"
            f"#SBATCH --job-name={job_name}\n"
            f"#SBATCH --time={time_limit}\n"
            f"#SBATCH --output=workspace_{session.workspace_id}/slurm_%j.out\n"
            f"#SBATCH --error=workspace_{session.workspace_id}/slurm_%j.err\n\n"
            f"{script_payload}\n"
        )

        # VRAM admission check (RNF-008) -- informational/gating only; the
        # dispatcher itself never changes based on this (see class docstring).
        await self._check_vram_admission(required_vram_gb)

        job_id = await self.dispatcher.dispatch(sbatch_script)

        # Save session status change
        await self.session_repo.save(session)

        return job_id

    async def _check_vram_admission(self, required_vram_gb: float) -> None:
        if required_vram_gb is None or self.vram_checker is None:
            return

        local_vram = await self.vram_checker.available_vram_gb()
        decision = self.scaling_decision.evaluate(required_vram_gb, local_vram)
        if decision.fits:
            return

        if self.reject_if_insufficient_vram:
            raise ValueError(decision.message)

        logger.warning(decision.message)
