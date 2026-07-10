"""Modal Cloud GPU dispatcher (RNF-008).

Real elastic Modal execution needs a Modal account + GPU and is infra-blocked
here; this stub returns a deterministic mock id (and warns) so the VRAM-based
scale-out decision path is fully exercisable locally.
"""
import logging

logger = logging.getLogger(__name__)

_MOCK_MODAL_JOB_ID = "modal_mock_job"


class ModalDispatcher:
    async def dispatch(self, sbatch_script: str) -> str:
        logger.warning(
            "ModalDispatcher: real Modal Cloud integration is not configured; "
            "returning a MOCK job id (%r). No job was submitted to Modal.",
            _MOCK_MODAL_JOB_ID,
        )
        return _MOCK_MODAL_JOB_ID
