from typing import Protocol


class EphemeralCredentialPort(Protocol):
    """Issues short-lived, single-use SSH credentials (RNF-003).

    Implemented by VaultClient (SSH secrets engine, OTP mode); injected into the
    Slurm dispatcher so cluster access uses ephemeral tokens instead of a static
    long-lived key.
    """

    async def get_ephemeral_ssh_token(self, username: str, target_ip: str = "") -> str:
        ...
