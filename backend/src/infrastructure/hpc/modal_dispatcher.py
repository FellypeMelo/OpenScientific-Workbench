"""REMOVED: Modal Cloud GPU dispatcher (RNF-008).

This project's architecture is locked to a single local Linux server (Docker
Compose, no external cloud/cluster) -- see the decision record in
`docs/planning/`. Cloud/remote-GPU dispatch (Modal) has been removed
entirely: there is no remote fallback for VRAM-heavy jobs, and nothing in
this codebase constructs or calls `ModalDispatcher` anymore.

`DispatchHPCJobUseCase` (`application/use_cases/dispatch_hpc_job.py`) no
longer accepts a `modal_dispatcher` argument. `Evo2ScalingDecision`
(`domain/services/evo2_scaling_decision.py`) no longer chooses a remote
dispatch target -- it now only reports whether a job's declared VRAM need
fits locally (an admission check), since "run remotely instead" is no longer
a real option.

This file (and the class below) is kept only for history/traceability, not
as a live code path. Do not wire it into `presentation/dependencies.py` or
any use case.
"""
import logging

logger = logging.getLogger(__name__)

_MOCK_MODAL_JOB_ID = "modal_mock_job"


class ModalDispatcher:
    """Dead code, retained for history only -- see module docstring. Nothing
    in this codebase constructs or calls this class anymore."""

    async def dispatch(self, sbatch_script: str) -> str:
        logger.warning(
            "ModalDispatcher.dispatch() was called, but Modal/cloud-GPU dispatch "
            "has been REMOVED from this project's architecture (single local "
            "Linux server, no external cluster). This code path should be "
            "unreachable -- returning a mock id (%r) only so a stray call does "
            "not crash, not because this is a supported feature.",
            _MOCK_MODAL_JOB_ID,
        )
        return _MOCK_MODAL_JOB_ID
