from enum import Enum


class JobStatus(str, Enum):
    """Normalised HPC job state (RF-006), decoupled from Slurm's raw state names."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"
