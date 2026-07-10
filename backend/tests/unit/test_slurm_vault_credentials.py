"""RNF-003: Slurm SSH must authenticate with a Vault-issued ephemeral OTP when a
credential provider is wired, instead of a static long-lived key file.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

import paramiko

from src.infrastructure.hpc.slurm_dispatcher import SlurmSSHDispatcher


def _fake_sbatch_client(job_id=b"Submitted batch job 555\n"):
    channel = MagicMock()
    channel.recv_exit_status.return_value = 0
    stdout = MagicMock()
    stdout.channel = channel
    stdout.read.return_value = job_id
    stderr = MagicMock()
    stderr.read.return_value = b""
    stdin = MagicMock()
    stdin.channel = channel
    client = MagicMock()
    client.exec_command.return_value = (stdin, stdout, stderr)
    return client


@pytest.mark.asyncio
async def test_dispatch_authenticates_with_vault_otp(monkeypatch):
    client = _fake_sbatch_client()
    monkeypatch.setattr(paramiko, "SSHClient", MagicMock(return_value=client))
    vault = MagicMock()
    vault.get_ephemeral_ssh_token = AsyncMock(return_value="OTP-XYZ")

    dispatcher = SlurmSSHDispatcher(
        host="h", username="u", key_path="/k", credential_provider=vault
    )

    job_id = await dispatcher.dispatch("#SBATCH --job-name=t\n")

    assert job_id == "555"
    vault.get_ephemeral_ssh_token.assert_awaited_once_with("u")
    client.connect.assert_called_once_with(
        hostname="h", username="u", password="OTP-XYZ", timeout=15
    )


@pytest.mark.asyncio
async def test_dispatch_without_provider_uses_static_key(monkeypatch):
    client = _fake_sbatch_client(b"Submitted batch job 1\n")
    monkeypatch.setattr(paramiko, "SSHClient", MagicMock(return_value=client))

    dispatcher = SlurmSSHDispatcher(host="h", username="u", key_path="/k")

    await dispatcher.dispatch("#SBATCH\n")

    client.connect.assert_called_once_with(
        hostname="h", username="u", key_filename="/k", timeout=15
    )
