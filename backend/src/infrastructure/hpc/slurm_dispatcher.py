"""
Slurm job dispatch adapter (Fase 4 - real paramiko SSH integration).

Design notes:
- Real dispatch (SSH connect + `sbatch`) is only attempted when
  `settings.SLURM_SSH_HOST`, `settings.SLURM_SSH_USER` and
  `settings.SLURM_SSH_KEY_PATH` are ALL configured. Any one of them missing is
  treated as "no real HPC gateway is reachable from here" (fresh checkout, CI
  runner, local dev machine) rather than an error: `dispatch()` falls back to
  the historical mock job id, but logs a loud warning so the fallback is never
  silently mistaken for a real submission.
- Host key handling: internal HPC login/gateway nodes are typically not
  pre-seeded in the calling machine's `known_hosts` (ephemeral bastion hosts,
  lab clusters provisioned per-project), so strict `RejectPolicy`/manual
  pinning would make this adapter unusable out of the box. We load whatever
  host keys the system already trusts via `load_system_host_keys()` and only
  fall back to `AutoAddPolicy` (trust-on-first-use) for hosts not already
  known -- the same tradeoff Paramiko's own test suite documents. This is a
  private, credentialed (SSH key) connection to an internal cluster gateway,
  not a public-internet endpoint, which is the standard context where
  TOFU/`AutoAddPolicy` is considered an acceptable risk.
- The remote `sbatch` script is piped over the command's stdin (no remote
  temp file / SFTP round trip needed): `ssh host sbatch <<< script`. This is
  simpler than writing+cleaning up a remote temp file and is exactly how a
  human operator would submit an inline script over SSH.
- The real job id is parsed from `sbatch`'s standard success message
  (`Submitted batch job 12345`) and returned as the bare numeric id (e.g.
  `"12345"`), matching what `squeue`/`scancel`/`sacct` expect. This
  intentionally differs from the mock's `"job_10492"` placeholder format --
  the mock string was never a real Slurm job id to begin with, so the real
  path returns the actual identifier instead of copying an invented format.
- The blocking Paramiko calls are executed in a worker thread via
  `asyncio.to_thread` so `dispatch()` (declared `async` by
  `HPCJobDispatcherPort`) does not block the event loop for the duration of
  the SSH round trip.
"""
import asyncio
import logging
import os
import re

import paramiko

from src.domain.ports.hpc_job_dispatcher import HPCJobDispatcherPort
from src.infrastructure.config import settings

logger = logging.getLogger(__name__)

# `sbatch`'s stdout on success is a single line: "Submitted batch job 12345".
_JOB_ID_PATTERN = re.compile(r"Submitted batch job (\d+)")

#: Deterministic placeholder returned when no real SSH gateway is configured.
_MOCK_JOB_ID = "job_10492"


class SlurmSSHDispatcher(HPCJobDispatcherPort):
    """
    Adapter implementing HPCJobDispatcherPort using a Paramiko SSH tunnel to a
    Slurm login/gateway node.
    """

    def __init__(self, host: str = None, username: str = None, key_path: str = None):
        # Legacy envs (`SLURM_HOST`/`SLURM_USER`) predate the Fase 4 SSH wiring
        # and are kept for backwards compatibility with any existing call
        # sites/config that only set those. They double as the connection
        # target when explicit SSH settings are absent.
        self.host = host or os.getenv("SLURM_HOST", "slurm-login.inst.edu")
        self.username = username or os.getenv("SLURM_USER", "scientist")

        # Dedicated SSH dispatch settings. Whether ALL of these resolve to a
        # real value is what actually gates the real-vs-mock branch below --
        # this makes "real dispatch is configured" an explicit, unambiguous
        # opt-in rather than inferred from the legacy defaults above (which
        # always resolve to *something*, even in local dev).
        self.ssh_host = host or settings.SLURM_SSH_HOST
        self.ssh_user = username or settings.SLURM_SSH_USER
        self.ssh_key_path = key_path or settings.SLURM_SSH_KEY_PATH

    @property
    def _is_configured(self) -> bool:
        return bool(self.ssh_host and self.ssh_user and self.ssh_key_path)

    async def dispatch(self, sbatch_script: str) -> str:
        """Submits the sbatch script to Slurm and returns a unique JobID."""
        if not self._is_configured:
            logger.warning(
                "SlurmSSHDispatcher: SLURM_SSH_HOST/SLURM_SSH_USER/SLURM_SSH_KEY_PATH "
                "are not fully configured (host=%r, user=%r, key_path=%r); returning "
                "a MOCK job id (%r). No job was actually submitted to a Slurm cluster.",
                self.ssh_host, self.ssh_user, self.ssh_key_path, _MOCK_JOB_ID,
            )
            return _MOCK_JOB_ID

        return await asyncio.to_thread(self._dispatch_sync, sbatch_script)

    def _dispatch_sync(self, sbatch_script: str) -> str:
        """Blocking Paramiko implementation, run off the event loop via `to_thread`."""
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=self.ssh_host,
                username=self.ssh_user,
                key_filename=self.ssh_key_path,
                timeout=15,
            )

            stdin, stdout, stderr = client.exec_command("sbatch", timeout=30)
            stdin.write(sbatch_script)
            stdin.flush()
            stdin.channel.shutdown_write()

            exit_status = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")

            if exit_status != 0:
                raise RuntimeError(
                    f"sbatch exited with status {exit_status} on {self.ssh_host}: {err.strip()}"
                )

            match = _JOB_ID_PATTERN.search(out)
            if not match:
                raise RuntimeError(
                    f"Could not parse a Slurm job id from sbatch output: {out!r} (stderr: {err!r})"
                )

            return match.group(1)
        finally:
            client.close()
