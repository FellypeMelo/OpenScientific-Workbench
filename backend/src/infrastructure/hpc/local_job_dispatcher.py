"""Local Redis-backed HPC job dispatcher (RF-006/RNF-003/RNF-008 gap closure).

Implements `HPCJobDispatcherPort` as `HPC_BACKEND=local` (the default, per
this project's locked single-local-server architecture -- one Linux box,
Docker Compose, no external cloud/cluster). Where `SlurmSSHDispatcher`
submits a compiled sbatch script to a *remote* cluster over SSH, this adapter
enqueues the SAME script onto a local Redis-backed RQ queue (`"osw-jobs"`),
consumed by a separate worker process (`scripts/run_worker.py`, or
`docker-compose.yml`'s `worker` service) that actually runs it -- through the
SAME real sandbox isolation (`BubblewrapSandboxDriver` via
`SandboxNodeExecutor`) that real DAG-node execution uses (RF-005), rather
than a second, parallel unsandboxed execution path.

Design notes:
- `dispatch()` enqueues `run_sandboxed_job` (a MODULE-LEVEL function, not a
  method or closure -- RQ pickles a reference to it by import path, so the
  worker process must be able to `import` this exact name) and returns the
  RQ job id. RQ's own synchronous API is wrapped in `asyncio.to_thread` so
  this coroutine never blocks the event loop, mirroring how
  `SlurmSSHDispatcher` wraps its blocking Paramiko calls.
- `poll_status()` looks the job up by id against the SAME Redis connection
  and maps RQ's `JobStatus` enum to this codebase's own normalised
  `JobStatus` (`domain/entities/job_status.py`). An id RQ has never seen
  (`NoSuchJobError`) maps to `JobStatus.UNKNOWN`, mirroring
  `SlurmSSHDispatcher.poll_status`'s "no gateway configured" fallback.
- `upload_file`/`download_file`: there is no *remote* host in the local
  backend -- the worker process shares the same workspace filesystem as the
  API process (see `docker-compose.yml`, both built from the same image).
  Implemented as real local filesystem copies (not no-ops) so callers written
  against the `HPCJobDispatcherPort` contract (stage input, dispatch, fetch
  output) keep working unmodified when `HPC_BACKEND` flips between "local"
  and "slurm".
"""
import asyncio
import logging
import os
import shutil
from typing import Optional

import redis
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job
from rq.job import JobStatus as RQJobStatus

from src.domain.entities.job_status import JobStatus
from src.domain.ports.hpc_job_dispatcher import HPCJobDispatcherPort
from src.infrastructure.config import settings

logger = logging.getLogger(__name__)

#: RQ queue name -- must match `docker-compose.yml`'s `worker` service
#: (`rq worker osw-jobs`) / `scripts/run_worker.py`.
QUEUE_NAME = "osw-jobs"

#: Maps RQ's raw job status to this codebase's normalised `JobStatus`
#: (RF-006). RQ has more granular pre-execution states (CREATED/SCHEDULED/
#: DEFERRED) than this project's enum distinguishes -- all of them mean
#: "not running yet", so they collapse to `PENDING`, mirroring how
#: `SlurmSSHDispatcher._STATE_MAP` collapses Slurm's PENDING/CONFIGURING.
_RQ_STATUS_MAP = {
    RQJobStatus.CREATED: JobStatus.PENDING,
    RQJobStatus.QUEUED: JobStatus.PENDING,
    RQJobStatus.SCHEDULED: JobStatus.PENDING,
    RQJobStatus.DEFERRED: JobStatus.PENDING,
    RQJobStatus.STARTED: JobStatus.RUNNING,
    RQJobStatus.FINISHED: JobStatus.COMPLETED,
    RQJobStatus.FAILED: JobStatus.FAILED,
    RQJobStatus.STOPPED: JobStatus.CANCELLED,
    RQJobStatus.CANCELED: JobStatus.CANCELLED,
}


def run_sandboxed_job(sbatch_script: str, workspace_root: str = "osw_workspace") -> dict:
    """RQ job entry point -- executed by the WORKER process (`rq worker
    osw-jobs`), never by the API process that calls `dispatch()`.

    Must stay a plain, importable, module-level function: RQ serialises a
    *reference* to it (`module:qualname`), not its bytecode, so whatever
    process runs the worker has to be able to `import
    src.infrastructure.hpc.local_job_dispatcher` and find this name.

    Runs `sbatch_script` -- the SAME `#SBATCH ...` header + payload text
    `DispatchHPCJobUseCase` compiles for the Slurm path -- as a bash script
    through the real sandbox machinery (`BubblewrapSandboxDriver` via
    `SandboxNodeExecutor`, see `infrastructure/sandbox/`) instead of a
    separate, unsandboxed `subprocess.run`. The `#SBATCH` directive lines are
    meaningless outside a real Slurm cluster; since they start with `#`, bash
    treats them as ordinary comments and simply skips them, executing the
    actual payload beneath -- so no script rewriting is needed to run the
    exact same compiled script locally.

    Returns a small JSON-serialisable result dict (RQ stores whatever this
    returns as the job's `.result` via its normal result mechanism) so a
    caller inspecting a finished job can see what actually happened, mirroring
    `SandboxNodeExecutor`'s `node.output` convention.
    """
    # Imported lazily (inside the function, not at module import time) so
    # importing THIS module -- which the API process does, to enqueue jobs --
    # never requires a working sandbox driver. Only the worker process, when
    # it actually executes a job, needs `BubblewrapSandboxDriver` to be
    # constructible (i.e. `bwrap` present and functional, per its fail-loud
    # contract -- see `infrastructure/sandbox/bubblewrap_driver.py`).
    from src.domain.entities.dag import DAGNode
    from src.infrastructure.sandbox.bubblewrap_driver import BubblewrapSandboxDriver
    from src.infrastructure.sandbox.sandbox_node_executor import SandboxNodeExecutor

    driver = BubblewrapSandboxDriver(workspace_root=workspace_root, runtime=settings.SANDBOX_RUNTIME)
    executor = SandboxNodeExecutor(driver)
    node = DAGNode(
        id="local-hpc-job",
        description="Locally-dispatched HPC job (HPC_BACKEND=local)",
        language="bash",
        command=sbatch_script,
    )
    reward = asyncio.run(executor.simulate(node))
    return {"reward": reward, "output": node.output}


class LocalJobDispatcher(HPCJobDispatcherPort):
    """Adapter implementing `HPCJobDispatcherPort` against a local Redis-backed
    RQ queue instead of a remote Slurm cluster (see module docstring)."""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        connection: Optional["redis.Redis"] = None,
        queue_name: str = QUEUE_NAME,
    ):
        # Same "allow tests to inject a fake client directly" pattern as
        # `RateLimitMiddleware` (see `presentation/middleware/rate_limit.py`):
        # lazily constructed on first use so importing/constructing this class
        # never opens a socket, and a test can pass `connection=` to avoid
        # monkeypatching `redis.from_url`.
        self._redis_url = redis_url or settings.REDIS_URL
        self._connection = connection
        self._queue_name = queue_name

    def _get_connection(self) -> "redis.Redis":
        if self._connection is None:
            self._connection = redis.from_url(self._redis_url)
        return self._connection

    def _get_queue(self) -> Queue:
        return Queue(self._queue_name, connection=self._get_connection())

    async def dispatch(self, sbatch_script: str) -> str:
        """Enqueues `sbatch_script` onto the local RQ queue and returns the
        RQ job id (RF-006)."""
        job = await asyncio.to_thread(self._get_queue().enqueue, run_sandboxed_job, sbatch_script)
        logger.info("LocalJobDispatcher: enqueued job %r onto queue %r.", job.id, self._queue_name)
        return job.id

    async def poll_status(self, job_id: str) -> JobStatus:
        """Returns the current status of a previously-dispatched local job
        (RF-006), or `JobStatus.UNKNOWN` if RQ has never seen this id."""
        try:
            job = await asyncio.to_thread(Job.fetch, job_id, self._get_connection())
        except NoSuchJobError:
            logger.warning("LocalJobDispatcher.poll_status: unknown job id %r.", job_id)
            return JobStatus.UNKNOWN

        rq_status = await asyncio.to_thread(job.get_status)
        return _RQ_STATUS_MAP.get(rq_status, JobStatus.UNKNOWN)

    async def upload_file(self, local_path: str, remote_path: str) -> None:
        """Stages an input file for the local worker (RF-006). There is no
        remote host in this backend -- `remote_path` is just another path on
        the SAME shared filesystem the worker reads from, so this is a real
        local file copy, not a no-op."""
        parent = os.path.dirname(remote_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        await asyncio.to_thread(shutil.copy, local_path, remote_path)

    async def download_file(self, remote_path: str, local_path: str) -> None:
        """Fetches a produced output file back from the local worker (RF-006).
        See `upload_file` -- a real local file copy, mirroring the "remote"
        naming from `HPCJobDispatcherPort` for interface compatibility with
        `SlurmSSHDispatcher`."""
        parent = os.path.dirname(local_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        await asyncio.to_thread(shutil.copy, remote_path, local_path)
