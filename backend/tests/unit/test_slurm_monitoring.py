"""RF-006: Slurm status polling (squeue) and SFTP file sync on top of the real
sbatch adapter. Paramiko is mocked at the transport boundary, same pattern as
test_slurm_dispatcher_real.py.
"""
import pytest
from unittest.mock import MagicMock

import paramiko

from src.domain.entities.job_status import JobStatus
from src.infrastructure.hpc.slurm_dispatcher import SlurmSSHDispatcher


def _fake_exec_client(exit_status=0, stdout_bytes=b"", stderr_bytes=b""):
    channel = MagicMock()
    channel.recv_exit_status.return_value = exit_status
    stdout = MagicMock()
    stdout.channel = channel
    stdout.read.return_value = stdout_bytes
    stderr = MagicMock()
    stderr.read.return_value = stderr_bytes
    stdin = MagicMock()
    client = MagicMock()
    client.exec_command.return_value = (stdin, stdout, stderr)
    return client


def _configured():
    return SlurmSSHDispatcher(host="h", username="u", key_path="/k")


@pytest.mark.asyncio
async def test_poll_status_parses_running(monkeypatch):
    client = _fake_exec_client(exit_status=0, stdout_bytes=b"RUNNING\n")
    monkeypatch.setattr(paramiko, "SSHClient", MagicMock(return_value=client))

    status = await _configured().poll_status("98765")

    assert status is JobStatus.RUNNING
    client.exec_command.assert_called_once_with("squeue -h -j 98765 -o %T", timeout=30)
    client.close.assert_called_once()


@pytest.mark.asyncio
async def test_poll_status_empty_queue_means_completed(monkeypatch):
    client = _fake_exec_client(exit_status=0, stdout_bytes=b"")
    monkeypatch.setattr(paramiko, "SSHClient", MagicMock(return_value=client))

    assert await _configured().poll_status("1") is JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_poll_status_unknown_when_not_configured():
    # host+user but no key -> not configured -> UNKNOWN, no SSH attempted.
    dispatcher = SlurmSSHDispatcher(host="h", username="u")
    assert dispatcher._is_configured is False
    assert await dispatcher.poll_status("1") is JobStatus.UNKNOWN


@pytest.mark.asyncio
async def test_poll_status_nonzero_exit_raises(monkeypatch):
    client = _fake_exec_client(exit_status=1, stderr_bytes=b"squeue: error: invalid job id")
    monkeypatch.setattr(paramiko, "SSHClient", MagicMock(return_value=client))

    with pytest.raises(RuntimeError, match="squeue failed"):
        await _configured().poll_status("bad")


@pytest.mark.asyncio
async def test_upload_file_puts_over_sftp(monkeypatch):
    client = MagicMock()
    sftp = MagicMock()
    client.open_sftp.return_value = sftp
    monkeypatch.setattr(paramiko, "SSHClient", MagicMock(return_value=client))

    await _configured().upload_file("/local/in.csv", "/remote/in.csv")

    sftp.put.assert_called_once_with("/local/in.csv", "/remote/in.csv")
    sftp.close.assert_called_once()
    client.close.assert_called_once()


@pytest.mark.asyncio
async def test_download_file_gets_over_sftp(monkeypatch):
    client = MagicMock()
    sftp = MagicMock()
    client.open_sftp.return_value = sftp
    monkeypatch.setattr(paramiko, "SSHClient", MagicMock(return_value=client))

    await _configured().download_file("/remote/out.pdb", "/local/out.pdb")

    sftp.get.assert_called_once_with("/remote/out.pdb", "/local/out.pdb")


@pytest.mark.asyncio
async def test_upload_file_noop_when_not_configured(monkeypatch):
    spy = MagicMock()
    monkeypatch.setattr(paramiko, "SSHClient", spy)

    await SlurmSSHDispatcher(host="h", username="u").upload_file("a", "b")

    spy.assert_not_called()  # never opened a connection
