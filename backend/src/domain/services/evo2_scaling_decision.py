class Evo2ScalingDecision:
    """Chooses where an Evo2/Boltz prediction runs based on VRAM demand (RNF-008).

    Pure logic: if the analysis needs more VRAM than is available locally, it must
    scale out to a remote GPU backend (Modal); otherwise it runs locally.
    """

    LOCAL = "local"
    REMOTE_MODAL = "remote_modal"

    def select_target(self, required_vram_gb: float, local_vram_gb: float) -> str:
        return self.REMOTE_MODAL if required_vram_gb > local_vram_gb else self.LOCAL
