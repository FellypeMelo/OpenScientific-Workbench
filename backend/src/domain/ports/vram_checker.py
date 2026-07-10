from typing import Protocol


class VRAMCheckerPort(Protocol):
    """Reports locally-available GPU VRAM in GB (RNF-008).

    Implemented against nvidia-smi / a GPU library in production; injected as a
    mock in tests so the scale-out decision is exercisable without a GPU.
    """

    async def available_vram_gb(self) -> float:
        ...
