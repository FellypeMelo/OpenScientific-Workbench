from uuid import UUID
from src.domain.entities.agent_session import AgentSession
from src.domain.ports.session_repository import SessionRepositoryPort
from src.domain.ports.hpc_job_dispatcher import HPCJobDispatcherPort
from src.domain.services.evo2_scaling_decision import Evo2ScalingDecision

class DispatchHPCJobUseCase:
    """
    Application use case for compiling and dispatching sbatch jobs.

    When a VRAM checker and a Modal dispatcher are wired and ``required_vram_gb``
    is supplied, the job scales out to the remote GPU backend if it exceeds
    locally-available VRAM (RNF-008); otherwise it goes to the Slurm dispatcher.
    """
    def __init__(
        self,
        session_repo: SessionRepositoryPort,
        dispatcher: HPCJobDispatcherPort,
        modal_dispatcher=None,
        vram_checker=None,
        scaling_decision: Evo2ScalingDecision = None,
    ):
        self.session_repo = session_repo
        self.dispatcher = dispatcher
        self.modal_dispatcher = modal_dispatcher
        self.vram_checker = vram_checker
        self.scaling_decision = scaling_decision or Evo2ScalingDecision()

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

        # Choose the execution backend based on VRAM demand (RNF-008).
        dispatcher = await self._select_dispatcher(required_vram_gb)
        job_id = await dispatcher.dispatch(sbatch_script)

        # Save session status change
        await self.session_repo.save(session)

        return job_id

    async def _select_dispatcher(self, required_vram_gb):
        if (
            required_vram_gb is None
            or self.vram_checker is None
            or self.modal_dispatcher is None
        ):
            return self.dispatcher

        local_vram = await self.vram_checker.available_vram_gb()
        target = self.scaling_decision.select_target(required_vram_gb, local_vram)
        if target == Evo2ScalingDecision.REMOTE_MODAL:
            return self.modal_dispatcher
        return self.dispatcher
