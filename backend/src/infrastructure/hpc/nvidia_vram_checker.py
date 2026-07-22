"""Real NVIDIA VRAM availability checker (RNF-008).

Implements `VRAMCheckerPort` (`domain/ports/vram_checker.py`) by shelling out
to `nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits` --
the standard, script-friendly way to query free GPU memory without pulling in
a CUDA/NVML Python binding as a hard dependency.

Design notes:
- Returns `0.0` (NOT a raised exception) when `nvidia-smi` is missing
  (`FileNotFoundError`) or its output can't be parsed as a number. This is an
  EXPECTED, tested branch -- this project's Windows dev sandbox, and any
  target Linux server that was never provisioned with an NVIDIA GPU, simply
  has no `nvidia-smi` binary at all -- not a genuine failure. A caller
  (`DispatchHPCJobUseCase`'s VRAM admission check, via `Evo2ScalingDecision`)
  treats "0 GB available" the same as "insufficient VRAM for any nonzero
  requirement", which is the correct, safe behavior on a GPU-less host: warn
  (and still run locally, since no remote GPU backend exists per this
  project's locked architecture) or reject, per the use case's configured
  policy.
- Multi-GPU hosts: `nvidia-smi` prints one CSV line per GPU. This reports the
  MAXIMUM free VRAM across all GPUs (not the sum) -- a single dispatched job
  runs on one GPU's worth of free memory (nothing in this codebase is
  GPU-sharding-aware), so summing would overstate what a single job can
  actually use.
"""
import asyncio
import logging
import subprocess

logger = logging.getLogger(__name__)

_NVIDIA_SMI_ARGV = ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"]

_MIB_PER_GB = 1024.0


class NvidiaVRAMChecker:
    """Adapter implementing `VRAMCheckerPort` against real GPU hardware."""

    async def available_vram_gb(self) -> float:
        return await asyncio.to_thread(self._query_sync)

    def _query_sync(self) -> float:
        try:
            result = subprocess.run(
                _NVIDIA_SMI_ARGV, capture_output=True, text=True, timeout=10, check=False
            )
        except FileNotFoundError:
            logger.info(
                "nvidia-smi not found on PATH; reporting 0.0 GB available VRAM "
                "(expected on a host with no NVIDIA GPU)."
            )
            return 0.0
        except subprocess.SubprocessError as exc:
            logger.warning(
                "nvidia-smi invocation failed (%s); reporting 0.0 GB available VRAM.", exc
            )
            return 0.0

        if result.returncode != 0:
            logger.warning(
                "nvidia-smi exited %s: %s; reporting 0.0 GB available VRAM.",
                result.returncode,
                result.stderr.strip(),
            )
            return 0.0

        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        try:
            free_mib_per_gpu = [float(line) for line in lines]
            max_free_mib = max(free_mib_per_gpu)
        except (ValueError, IndexError) as exc:
            logger.warning(
                "Could not parse nvidia-smi output %r (%s); reporting 0.0 GB available VRAM.",
                result.stdout,
                exc,
            )
            return 0.0

        return max_free_mib / _MIB_PER_GB
