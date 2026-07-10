from typing import Protocol

from src.domain.entities.job_status import JobStatus


class HPCJobDispatcherPort(Protocol):
    """
    Domain port interface for dispatching and monitoring long-running jobs on
    Slurm clusters.
    """
    async def dispatch(self, sbatch_script: str) -> str:
        """Submits the sbatch script to Slurm and returns a unique JobID."""
        ...

    async def poll_status(self, job_id: str) -> JobStatus:
        """Returns the current status of a dispatched job (RF-006)."""
        ...

    async def upload_file(self, local_path: str, remote_path: str) -> None:
        """Stages a local input file onto the cluster filesystem (RF-006)."""
        ...

    async def download_file(self, remote_path: str, local_path: str) -> None:
        """Fetches a produced output file back from the cluster (RF-006)."""
        ...
