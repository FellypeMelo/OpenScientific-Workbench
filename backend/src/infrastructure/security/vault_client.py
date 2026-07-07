"""
HashiCorp Vault ephemeral-credential adapter (Fase 4 - real `hvac` integration).

Design notes:
- Falls back to a deterministic mock string whenever `self.vault_token` is
  falsy -- mirroring the same "real infra not configured" gating pattern used
  by the other Fase 4 adapters (Neo4j/Slurm), so a fresh checkout / CI runner
  / local dev machine without a running Vault server still boots and the test
  suite stays deterministic.
- Engine choice: Vault's **SSH secrets engine in One-Time-Password (OTP) mode**
  (`client.secrets.ssh.generate_ssh_credentials`) is used, not the Transit or
  PKI engines. This is the engine that most literally matches "ephemeral SSH
  token": each call mints a brand-new, single-use OTP scoped to one
  `username`/`ip` pair that Vault's `vault-ssh-helper` on the target host
  verifies and then discards after first use (or the role's configured TTL
  elapses) -- i.e. exactly the "5-minute transient token" described in this
  method's docstring. Transit issues encryption/signing keys (no notion of an
  SSH login credential) and PKI issues long(er)-lived certificates, not
  single-use tokens, so neither matches "ephemeral SSH token" semantics as
  directly as the SSH-OTP engine does.
- `hvac.Client(...)` is constructed fresh per call rather than cached: it is a
  thin `requests.Session` wrapper with no persistent connection to keep alive
  across calls (unlike the Neo4j driver's connection pool), so there is no
  real benefit to caching it here, and creating it per-call keeps this
  adapter trivially stateless/thread-safe.
"""
import os

import hvac

from src.infrastructure.config import settings


class VaultClient:
    """
    Adapter for retrieving ephemeral credentials and tokens from HashiCorp Vault (Zero-Trust).
    """
    def __init__(self, vault_url: str = None, vault_token: str = None, ssh_role: str = None):
        self.vault_url = vault_url or os.getenv("VAULT_ADDR", settings.VAULT_ADDR)
        self.vault_token = vault_token if vault_token is not None else os.getenv("VAULT_TOKEN", settings.VAULT_TOKEN)
        self.ssh_role = ssh_role or os.getenv("VAULT_SSH_ROLE", settings.VAULT_SSH_ROLE)

    async def get_ephemeral_ssh_token(self, username: str, target_ip: str = "") -> str:
        """
        Retrieves a one-time-use, short-lived SSH credential ("token") from
        Vault's SSH secrets engine (OTP mode) for `username`.

        `target_ip` is the remote host the OTP will be validated against by
        `vault-ssh-helper` on that host; it may be left empty when the Vault
        SSH role is configured as a "zero address" role (valid for any host),
        which is the common setup for a fleet of interchangeable HPC login
        nodes.
        """
        if not self.vault_token:
            return f"ephemeral_mock_ssh_token_{username}"

        client = hvac.Client(url=self.vault_url, token=self.vault_token)
        response = client.secrets.ssh.generate_ssh_credentials(
            name=self.ssh_role,
            username=username,
            ip=target_ip,
        )
        data = response.get("data") or {}
        otp = data.get("key")
        if not otp:
            raise RuntimeError(
                f"Vault SSH secrets engine (role={self.ssh_role!r}) did not return an OTP "
                f"key for username={username!r}: {response!r}"
            )
        return otp
