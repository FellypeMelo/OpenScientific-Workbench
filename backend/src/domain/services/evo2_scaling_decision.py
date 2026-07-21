from dataclasses import dataclass


@dataclass(frozen=True)
class VRAMAdmissionDecision:
    """Result of a VRAM admission check (RNF-008): whether a job's declared
    VRAM requirement fits within what is locally available, plus a
    human-readable explanation a caller can log or surface to a client."""

    fits: bool
    required_vram_gb: float
    available_vram_gb: float

    @property
    def message(self) -> str:
        if self.fits:
            return (
                f"Required VRAM ({self.required_vram_gb:.1f} GB) fits within "
                f"locally available VRAM ({self.available_vram_gb:.1f} GB)."
            )
        return (
            f"Required VRAM ({self.required_vram_gb:.1f} GB) exceeds locally "
            f"available VRAM ({self.available_vram_gb:.1f} GB). No remote GPU "
            "backend is configured -- cloud/cluster GPU dispatch (Modal) was "
            "removed entirely per this project's locked single-local-server "
            "architecture, so there is no remote fallback to scale out to."
        )


class Evo2ScalingDecision:
    """VRAM admission-check logic for GPU-heavy HPC jobs (RNF-008).

    Historical note: this class used to CHOOSE a dispatch target -- run
    locally, or scale out to a remote GPU backend (Modal Cloud) -- whenever a
    job's declared VRAM need exceeded what was locally available. Modal/
    remote-GPU dispatch has since been removed entirely (this project's
    locked architecture is one local Linux server, Docker Compose, no
    external cloud/cluster): there is no remote target left to route to.

    Its role is now purely informational/admission: report whether a job
    fits in what's locally available, so a caller
    (`application/use_cases/dispatch_hpc_job.py::DispatchHPCJobUseCase`) can
    decide, per its own policy, to warn-and-still-run-locally (the default --
    the job dispatches anyway, since there is nowhere else for it to go) or
    reject the dispatch outright with a clear, actionable message when the
    gap is large enough that running it is essentially certain to fail
    (out-of-memory) rather than merely slow.
    """

    def evaluate(self, required_vram_gb: float, local_vram_gb: float) -> VRAMAdmissionDecision:
        return VRAMAdmissionDecision(
            fits=required_vram_gb <= local_vram_gb,
            required_vram_gb=required_vram_gb,
            available_vram_gb=local_vram_gb,
        )
