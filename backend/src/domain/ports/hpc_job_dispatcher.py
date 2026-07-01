from typing import Protocol

class HPCJobDispatcherPort(Protocol):
    """
    Domain port interface for dispatching long-running jobs to Slurm clusters.
    """
    async def dispatch(self, sbatch_script: str) -> str:
        """Submits the sbatch script to Slurm and returns a unique JobID."""
        ...
