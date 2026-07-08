"""
Real-path tests for `SlurmSSHDispatcher` (Fase 4). Paramiko's `SSHClient` is
mocked at the transport boundary (`paramiko.SSHClient`/`exec_command`) so these
tests exercise the *real* dispatch code path (connect, write sbatch script to
stdin, parse `Submitted batch job N`, close the connection) without requiring
an actual Slurm cluster -- which does not exist in this sandbox.
"""
import pytest
from unittest.mock import MagicMock

import paramiko

from src.infrastructure.hpc import slurm_dispatcher as slurm_dispatcher_module
from src.infrastructure.hpc.slurm_dispatcher import SlurmSSHDispatcher


def _make_fake_ssh_client(exit_status: int = 0, stdout_bytes: bytes = b"", stderr_bytes: bytes = b""):
    """Builds a MagicMock standing in for a connected `paramiko.SSHClient`."""
    channel = MagicMock(name="channel")
    channel.recv_exit_status.return_value = exit_status

    stdin = MagicMock(name="stdin")
    stdin.channel = channel

    stdout = MagicMock(name="stdout")
    stdout.channel = channel
    stdout.read.return_value = stdout_bytes

    stderr = MagicMock(name="stderr")
    stderr.read.return_value = stderr_bytes

    client = MagicMock(name="ssh_client")
    client.exec_command.return_value = (stdin, stdout, stderr)
    return client, stdin, stdout, stderr, channel


@pytest.mark.asyncio
async def test_slurm_dispatcher_real_path_parses_job_id(monkeypatch):
    client, stdin, stdout, stderr, channel = _make_fake_ssh_client(
        exit_status=0, stdout_bytes=b"Submitted batch job 98765\n"
    )
    monkeypatch.setattr(paramiko, "SSHClient", MagicMock(return_value=client))

    dispatcher = SlurmSSHDispatcher(
        host="hpc-gateway.internal", username="scientist", key_path="/keys/id_rsa"
    )
    assert dispatcher._is_configured is True

    job_id = await dispatcher.dispatch("#SBATCH --job-name=test\necho hi\n")

    assert job_id == "98765"

    # Real connection parameters were used.
    client.connect.assert_called_once_with(
        hostname="hpc-gateway.internal",
        username="scientist",
        key_filename="/keys/id_rsa",
        timeout=15,
    )
    client.exec_command.assert_called_once_with("sbatch", timeout=30)

    # The sbatch script content was actually written to stdin and EOF signaled.
    stdin.write.assert_called_once_with("#SBATCH --job-name=test\necho hi\n")
    stdin.channel.shutdown_write.assert_called_once()

    # Connection is always closed.
    client.close.assert_called_once()


@pytest.mark.asyncio
async def test_slurm_dispatcher_real_path_via_settings(monkeypatch):
    """Real dispatch also activates when params come from `settings`, not just
    explicit constructor args."""
    client, stdin, stdout, stderr, channel = _make_fake_ssh_client(
        exit_status=0, stdout_bytes=b"Submitted batch job 111\n"
    )
    monkeypatch.setattr(paramiko, "SSHClient", MagicMock(return_value=client))

    monkeypatch.setattr(slurm_dispatcher_module.settings, "SLURM_SSH_HOST", "login.cluster.edu")
    monkeypatch.setattr(slurm_dispatcher_module.settings, "SLURM_SSH_USER", "svc_hpc")
    monkeypatch.setattr(slurm_dispatcher_module.settings, "SLURM_SSH_KEY_PATH", "/keys/svc_hpc")

    dispatcher = SlurmSSHDispatcher()
    assert dispatcher._is_configured is True

    job_id = await dispatcher.dispatch("#SBATCH --job-name=test\n")
    assert job_id == "111"
    client.connect.assert_called_once_with(
        hostname="login.cluster.edu",
        username="svc_hpc",
        key_filename="/keys/svc_hpc",
        timeout=15,
    )


@pytest.mark.asyncio
async def test_slurm_dispatcher_real_path_nonzero_exit_raises(monkeypatch):
    client, stdin, stdout, stderr, channel = _make_fake_ssh_client(
        exit_status=1, stdout_bytes=b"", stderr_bytes=b"sbatch: error: invalid partition"
    )
    monkeypatch.setattr(paramiko, "SSHClient", MagicMock(return_value=client))

    dispatcher = SlurmSSHDispatcher(host="h", username="u", key_path="/k")

    with pytest.raises(RuntimeError, match="invalid partition"):
        await dispatcher.dispatch("#SBATCH --job-name=test\n")

    # Connection must still be closed even on failure.
    client.close.assert_called_once()


@pytest.mark.asyncio
async def test_slurm_dispatcher_real_path_unparseable_output_raises(monkeypatch):
    client, stdin, stdout, stderr, channel = _make_fake_ssh_client(
        exit_status=0, stdout_bytes=b"something unexpected\n"
    )
    monkeypatch.setattr(paramiko, "SSHClient", MagicMock(return_value=client))

    dispatcher = SlurmSSHDispatcher(host="h", username="u", key_path="/k")

    with pytest.raises(RuntimeError, match="Could not parse a Slurm job id"):
        await dispatcher.dispatch("#SBATCH --job-name=test\n")


@pytest.mark.asyncio
async def test_slurm_dispatcher_mock_fallback_when_partially_configured():
    """Only host+user configured (no key path) must still fall back to mock --
    partial configuration is not real configuration."""
    dispatcher = SlurmSSHDispatcher(host="hpc-gateway.internal", username="scientist")
    assert dispatcher._is_configured is False

    job_id = await dispatcher.dispatch("#SBATCH --job-name=test\n")
    assert job_id == "job_10492"
