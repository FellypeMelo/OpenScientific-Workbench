"""Unit tests for `POST /api/v1/sessions/{session_id}/hpc/jobs` and
`GET /api/v1/sessions/{session_id}/hpc/jobs/{job_id}`
(`presentation/routes/hpc.py`, RF-006/RNF-008 gap closure).

The `HPCJobDispatcherPort` is faked via `app.dependency_overrides` (same
pattern `test_workspace_routes.py` uses for `StorageManagerPort`) -- these
tests are about the route/wiring/ownership-check layer, not re-testing
`LocalJobDispatcher`/`SlurmSSHDispatcher` themselves (covered by
`test_local_job_dispatcher.py`/`test_slurm_dispatcher_real.py`).

Session/workspace repos are also overridden with the SAME in-memory mocks
`test_evo2_scaling.py`/`test_create_session.py` use (`MockSessionRepository`/
`MockWorkspaceRepository`), not the real DB-backed ones: `AgentSession`'s
state machine (`domain/entities/agent_session.py`) only allows the
`DAG_GENERATION -> EXECUTING_HPC` transition `DispatchHPCJobUseCase.execute`
requires from a session that has already been through DAG planning, which
nothing reachable over HTTP parks a session in today (`SubmitTaskUseCase`
transits through `DAG_GENERATION` and back out again within one call, see
`application/use_cases/submit_task.py`) -- exactly why the PRE-EXISTING
`test_dispatch_hpc_job.py`/`test_evo2_scaling.py` unit tests construct their
`AgentSession` directly in `DAG_GENERATION` status rather than going through
`POST /sessions`. These route tests do the same, just via an injected
repository instead of direct construction, so ownership (IDOR) enforcement
-- the actual new logic in `routes/hpc.py` -- is still exercised for real.
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.domain.entities.agent_session import AgentSession
from src.domain.entities.job_status import JobStatus
from src.domain.entities.workspace import Workspace
from src.domain.ports.hpc_job_dispatcher import HPCJobDispatcherPort
from src.domain.ports.vram_checker import VRAMCheckerPort
from src.presentation.dependencies import (
    get_hpc_dispatcher,
    get_session_repository,
    get_vram_checker,
    get_workspace_repository,
)
from src.presentation.main import app
from src.presentation.middleware.jwt_auth import create_access_token
from tests.unit.test_create_session import MockSessionRepository, MockWorkspaceRepository

client = TestClient(app)


class _FakeDispatcher(HPCJobDispatcherPort):
    def __init__(self):
        self.dispatched_scripts = []
        self.status_by_job_id = {}

    async def dispatch(self, sbatch_script: str) -> str:
        self.dispatched_scripts.append(sbatch_script)
        return "fake_job_1"

    async def poll_status(self, job_id: str) -> JobStatus:
        return self.status_by_job_id.get(job_id, JobStatus.UNKNOWN)

    async def upload_file(self, local_path: str, remote_path: str) -> None:
        pass

    async def download_file(self, remote_path: str, local_path: str) -> None:
        pass


class _FakeVRAMChecker(VRAMCheckerPort):
    def __init__(self, available_gb: float = 999.0):
        self.available_gb = available_gb

    async def available_vram_gb(self) -> float:
        return self.available_gb


@pytest.fixture
def _repos():
    session_repo = MockSessionRepository()
    workspace_repo = MockWorkspaceRepository()
    app.dependency_overrides[get_session_repository] = lambda: session_repo
    app.dependency_overrides[get_workspace_repository] = lambda: workspace_repo
    try:
        yield session_repo, workspace_repo
    finally:
        app.dependency_overrides.pop(get_session_repository, None)
        app.dependency_overrides.pop(get_workspace_repository, None)


@pytest.fixture
def _dispatcher():
    fake = _FakeDispatcher()
    app.dependency_overrides[get_hpc_dispatcher] = lambda: fake
    app.dependency_overrides[get_vram_checker] = lambda: _FakeVRAMChecker()
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_hpc_dispatcher, None)
        app.dependency_overrides.pop(get_vram_checker, None)


async def _seed_owned_session(session_repo, workspace_repo, owner_id):
    """Materializes a workspace owned by `owner_id` plus a session belonging
    to it, already in `DAG_GENERATION` status -- the precondition
    `DispatchHPCJobUseCase.execute` requires (see module docstring)."""
    workspace = Workspace(owner_id=owner_id, fs_mount_path=f"workspace_{uuid4()}")
    await workspace_repo.save(workspace)
    session = AgentSession(workspace_id=workspace.id, session_status="DAG_GENERATION")
    await session_repo.save(session)
    return session, workspace


def _auth_headers(user_id=None) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id or uuid4(), iam_role='scientist')}"}


def test_dispatch_hpc_job_success(_repos, _dispatcher):
    session_repo, workspace_repo = _repos
    owner_id = uuid4()

    import asyncio

    session, _ = asyncio.run(_seed_owned_session(session_repo, workspace_repo, owner_id))

    response = client.post(
        f"/api/v1/sessions/{session.id}/hpc/jobs",
        json={"job_name": "boltz_predict", "script_payload": "python run_boltz.py"},
        headers=_auth_headers(owner_id),
    )

    assert response.status_code == 201
    assert response.json() == {"job_id": "fake_job_1"}
    assert len(_dispatcher.dispatched_scripts) == 1
    assert "python run_boltz.py" in _dispatcher.dispatched_scripts[0]
    assert "#SBATCH --job-name=boltz_predict" in _dispatcher.dispatched_scripts[0]

    updated = asyncio.run(session_repo.get_by_id(session.id))
    assert updated.session_status == "EXECUTING_HPC"


def test_dispatch_hpc_job_requires_auth(_repos, _dispatcher):
    response = client.post(
        f"/api/v1/sessions/{uuid4()}/hpc/jobs",
        json={"job_name": "x", "script_payload": "echo hi"},
    )
    assert response.status_code == 401


def test_dispatch_hpc_job_nonexistent_session_returns_404(_repos, _dispatcher):
    response = client.post(
        f"/api/v1/sessions/{uuid4()}/hpc/jobs",
        json={"job_name": "x", "script_payload": "echo hi"},
        headers=_auth_headers(),
    )
    assert response.status_code == 404
    assert _dispatcher.dispatched_scripts == []


def test_dispatch_hpc_job_owned_by_another_user_returns_404(_repos, _dispatcher):
    session_repo, workspace_repo = _repos
    owner_id = uuid4()
    attacker_id = uuid4()

    import asyncio

    session, _ = asyncio.run(_seed_owned_session(session_repo, workspace_repo, owner_id))

    response = client.post(
        f"/api/v1/sessions/{session.id}/hpc/jobs",
        json={"job_name": "x", "script_payload": "echo hi"},
        headers=_auth_headers(attacker_id),
    )

    assert response.status_code == 404
    assert _dispatcher.dispatched_scripts == []


def test_get_hpc_job_status_success(_repos, _dispatcher):
    session_repo, workspace_repo = _repos
    owner_id = uuid4()
    _dispatcher.status_by_job_id["fake_job_1"] = JobStatus.RUNNING

    import asyncio

    session, _ = asyncio.run(_seed_owned_session(session_repo, workspace_repo, owner_id))

    response = client.get(
        f"/api/v1/sessions/{session.id}/hpc/jobs/fake_job_1",
        headers=_auth_headers(owner_id),
    )

    assert response.status_code == 200
    assert response.json() == {"job_id": "fake_job_1", "status": "RUNNING"}


def test_get_hpc_job_status_owned_by_another_user_returns_404(_repos, _dispatcher):
    session_repo, workspace_repo = _repos
    owner_id = uuid4()
    attacker_id = uuid4()

    import asyncio

    session, _ = asyncio.run(_seed_owned_session(session_repo, workspace_repo, owner_id))

    response = client.get(
        f"/api/v1/sessions/{session.id}/hpc/jobs/fake_job_1",
        headers=_auth_headers(attacker_id),
    )

    assert response.status_code == 404


def test_get_hpc_job_status_requires_auth(_repos, _dispatcher):
    response = client.get(f"/api/v1/sessions/{uuid4()}/hpc/jobs/fake_job_1")
    assert response.status_code == 401


def test_dispatch_hpc_job_rejects_when_vram_insufficient_in_strict_mode(monkeypatch, _repos, _dispatcher):
    """`required_vram_gb` exceeding what's available maps to a 400 -- proves
    the route surfaces `DispatchHPCJobUseCase`'s `ValueError` cleanly, not a
    raw 500, when strict VRAM admission is requested."""
    import asyncio

    import src.presentation.routes.hpc as hpc_routes

    session_repo, workspace_repo = _repos
    owner_id = uuid4()
    session, _ = asyncio.run(_seed_owned_session(session_repo, workspace_repo, owner_id))

    original_use_case_cls = hpc_routes.DispatchHPCJobUseCase

    def _strict_use_case(*args, **kwargs):
        kwargs["reject_if_insufficient_vram"] = True
        return original_use_case_cls(*args, **kwargs)

    monkeypatch.setattr(hpc_routes, "DispatchHPCJobUseCase", _strict_use_case)
    app.dependency_overrides[get_vram_checker] = lambda: _FakeVRAMChecker(available_gb=1.0)

    response = client.post(
        f"/api/v1/sessions/{session.id}/hpc/jobs",
        json={
            "job_name": "evo2",
            "script_payload": "python evo2.py",
            "required_vram_gb": 48,
        },
        headers=_auth_headers(owner_id),
    )

    assert response.status_code == 400
    assert "exceeds locally available VRAM" in response.json()["detail"]
