from uuid import UUID
from src.domain.entities.agent_session import AgentSession
from src.domain.ports.session_repository import SessionRepositoryPort
from src.domain.ports.hpc_job_dispatcher import HPCJobDispatcherPort

class DispatchHPCJobUseCase:
    """
    Application use case for compiling and dispatching sbatch jobs to Slurm clusters.
    """
    def __init__(
        self,
        session_repo: SessionRepositoryPort,
        dispatcher: HPCJobDispatcherPort
    ):
        self.session_repo = session_repo
        self.dispatcher = dispatcher

    async def execute(self, session_id: UUID, job_name: str, script_payload: str, time_limit: str = "01:00:00") -> str:
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

        # Dispatch job via the adapter port
        job_id = await self.dispatcher.dispatch(sbatch_script)

        # Save session status change
        await self.session_repo.save(session)
        
        return job_id
