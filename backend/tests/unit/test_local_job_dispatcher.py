"""Unit tests for `LocalJobDispatcher` (RF-006/RNF-008 gap closure --
HPC_BACKEND=local, the default).

The actual Redis/RQ transport boundary (`rq.Queue`/`rq.job.Job`, which talk
to a real Redis connection under the hood) is faked here, mirroring how
`test_slurm_dispatcher_real.py` fakes `paramiko.SSHClient` -- no live Redis
is required to run this suite. `run_sandboxed_job` (the RQ job entry point
actually executed by a worker process) is exercised for real against
`SANDBOX_RUNTIME=mock` -- a genuinely configured, already-tested execution
mode of `BubblewrapSandboxDriver` (see `test_bubblewrap_driver.py`), not a
synthetic double -- so this suite also proves the job function really wires
into the same sandbox machinery `SandboxNodeExecutor` uses for RF-005 DAG
nodes, without needing a real `bwrap` binary on this test host.
"""
import pytest
from rq.exceptions import NoSuchJobError
from rq.job import JobStatus as RQJobStatus

import src.infrastructure.hpc.local_job_dispatcher as local_job_dispatcher_module
from src.domain.entities.job_status import JobStatus
from src.infrastructure.config import settings
from src.infrastructure.hpc.local_job_dispatcher import (
    QUEUE_NAME,
    LocalJobDispatcher,
    run_sandboxed_job,
)


class _FakeJob:
    def __init__(self, job_id: str, status: RQJobStatus = RQJobStatus.QUEUED):
        self.id = job_id
        self._status = status

    def get_status(self, refresh: bool = True) -> RQJobStatus:
        return self._status


class _FakeQueue:
    """Stand-in for `rq.Queue` -- records what got enqueued instead of
    actually touching Redis."""

    instances = []

    def __init__(self, name, connection=None):
        self.name = name
        self.connection = connection
        self.enqueued_calls = []
        _FakeQueue.instances.append(self)

    def enqueue(self, func, *args, **kwargs):
        self.enqueued_calls.append((func, args, kwargs))
        return _FakeJob("rq_job_abc123")


class _FakeJobRegistry:
    """Stand-in for `rq.job.Job` -- only the `.fetch` classmethod used by
    `LocalJobDispatcher.poll_status` is faked."""

    jobs: dict = {}

    @staticmethod
    def fetch(job_id, connection=None, serializer=None):
        if job_id not in _FakeJobRegistry.jobs:
            raise NoSuchJobError(f"No such job {job_id!r}")
        return _FakeJobRegistry.jobs[job_id]


@pytest.fixture(autouse=True)
def _reset_fakes():
    _FakeQueue.instances = []
    _FakeJobRegistry.jobs = {}
    yield


@pytest.mark.asyncio
async def test_dispatch_enqueues_run_sandboxed_job_and_returns_job_id(monkeypatch):
    monkeypatch.setattr(local_job_dispatcher_module, "Queue", _FakeQueue)

    dispatcher = LocalJobDispatcher(connection=object())
    script = "#!/bin/bash\n#SBATCH --job-name=x\necho hi\n"

    job_id = await dispatcher.dispatch(script)

    assert job_id == "rq_job_abc123"
    assert len(_FakeQueue.instances) == 1
    queue = _FakeQueue.instances[0]
    assert queue.name == QUEUE_NAME
    assert len(queue.enqueued_calls) == 1
    func, args, kwargs = queue.enqueued_calls[0]
    assert func is run_sandboxed_job
    assert args == (script,)
    assert kwargs == {}


@pytest.mark.parametrize(
    "rq_status,expected",
    [
        (RQJobStatus.CREATED, JobStatus.PENDING),
        (RQJobStatus.QUEUED, JobStatus.PENDING),
        (RQJobStatus.SCHEDULED, JobStatus.PENDING),
        (RQJobStatus.DEFERRED, JobStatus.PENDING),
        (RQJobStatus.STARTED, JobStatus.RUNNING),
        (RQJobStatus.FINISHED, JobStatus.COMPLETED),
        (RQJobStatus.FAILED, JobStatus.FAILED),
        (RQJobStatus.STOPPED, JobStatus.CANCELLED),
        (RQJobStatus.CANCELED, JobStatus.CANCELLED),
    ],
)
@pytest.mark.asyncio
async def test_poll_status_maps_rq_status_to_job_status(monkeypatch, rq_status, expected):
    monkeypatch.setattr(local_job_dispatcher_module, "Job", _FakeJobRegistry)
    _FakeJobRegistry.jobs["job-1"] = _FakeJob("job-1", rq_status)

    dispatcher = LocalJobDispatcher(connection=object())
    result = await dispatcher.poll_status("job-1")

    assert result == expected


@pytest.mark.asyncio
async def test_poll_status_unknown_job_returns_unknown(monkeypatch):
    monkeypatch.setattr(local_job_dispatcher_module, "Job", _FakeJobRegistry)

    dispatcher = LocalJobDispatcher(connection=object())
    result = await dispatcher.poll_status("never-seen")

    assert result == JobStatus.UNKNOWN


@pytest.mark.asyncio
async def test_upload_file_copies_local_file(tmp_path):
    source = tmp_path / "input.txt"
    source.write_text("some data")
    dest = tmp_path / "staged" / "input.txt"

    dispatcher = LocalJobDispatcher(connection=object())
    await dispatcher.upload_file(str(source), str(dest))

    assert dest.read_text() == "some data"


@pytest.mark.asyncio
async def test_download_file_copies_local_file(tmp_path):
    source = tmp_path / "produced_output.txt"
    source.write_text("results")
    dest = tmp_path / "downloaded" / "output.txt"

    dispatcher = LocalJobDispatcher(connection=object())
    await dispatcher.download_file(str(source), str(dest))

    assert dest.read_text() == "results"


def test_run_sandboxed_job_executes_through_sandbox_machinery(monkeypatch, tmp_path):
    """Exercises the REAL RQ job entry point (not a fake) against
    `SANDBOX_RUNTIME=mock` -- proves it actually builds a `DAGNode` and drives
    it through `SandboxNodeExecutor`/`BubblewrapSandboxDriver`, the SAME
    machinery RF-005 DAG-node execution uses, instead of a parallel
    unsandboxed path."""
    monkeypatch.setattr(settings, "SANDBOX_RUNTIME", "mock")

    result = run_sandboxed_job("#!/bin/bash\necho hi\n", workspace_root=str(tmp_path))

    assert result["reward"] == 1.0
    assert result["output"] == {"stdout": "Mock execution output: 42", "exit_code": 0}


def test_run_sandboxed_job_nonzero_exit_maps_to_negative_reward(monkeypatch, tmp_path):
    """`SANDBOX_RUNTIME=subprocess` with `subprocess.run` faked at the same
    transport boundary `test_bubblewrap_driver.py` uses (no real `bash`
    invocation needed on this test host) -- proves a failing command's exit
    code really propagates all the way through `run_sandboxed_job` to a
    negative reward, not just the happy path."""
    import types

    import src.infrastructure.sandbox.bubblewrap_driver as bw

    monkeypatch.setattr(settings, "SANDBOX_RUNTIME", "subprocess")
    monkeypatch.setattr(
        bw.subprocess,
        "run",
        lambda argv, **kwargs: types.SimpleNamespace(stdout="", stderr="boom", returncode=1),
    )

    result = run_sandboxed_job("exit 1\n", workspace_root=str(tmp_path))

    assert result["reward"] == -1.0
    assert result["output"]["exit_code"] == 1
