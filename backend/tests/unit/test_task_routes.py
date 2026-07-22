"""RF-001/RF-002: POST /sessions/{session_id}/tasks -- the live wiring of
MCTSOrchestrator + SubmitTaskUseCase + NumericReviewer behind an SSE route.

Mirrors `test_presentation_routes.py`'s chat-route test style: the BYOK
`ModelProviderPort` is faked at the `ModelClientFactory.get_client` boundary
(the actual transport edge), session/workspace ownership goes through the real
DB-backed repositories (via the autouse `_isolated_test_database` fixture in
`conftest.py`), and nothing about domain business logic is faked.

RF-005 gap-closure phase: the route's default `execution_mode` is now
`"sandbox"` (real code execution -- see `presentation/routes/tasks.py`'s
module docstring), not `"llm"`. The tests below that specifically exercise
the LLM-node-executor / actor-critic event sequence pin
`"execution_mode": "llm"` explicitly so they keep asserting that path
regardless of the route's default; `test_submit_task_stream_sandbox_mode_*`
and `test_submit_task_stream_sandbox_unavailable_returns_503` cover the new
default path itself.
"""
import json
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

import src.infrastructure.sandbox.bubblewrap_driver as bubblewrap_driver
import src.presentation.dependencies as dependencies
from src.presentation.main import app
from src.presentation.middleware.jwt_auth import create_access_token

client = TestClient(app)

_AUTH_HEADERS = {"Authorization": f"Bearer {create_access_token(uuid4(), iam_role='scientist')}"}

_PLAN_JSON = json.dumps(
    {
        "nodes": [
            {"id": "n1", "description": "load sequence data", "dependencies": []},
            {"id": "n2", "description": "run alignment", "dependencies": ["n1"]},
        ]
    }
)


def _create_session() -> str:
    response = client.post(
        "/api/v1/sessions",
        json={"workspace_id": str(uuid4())},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 201
    return response.json()["id"]


def _parse_sse_events(body: str):
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


class _FakeTaskClient:
    """Stand-in `ModelProviderPort`: the FIRST `generate_response` call is
    `LLMTaskPlanner.plan()` (always exactly one call, before any node
    simulation -- see `MCTSOrchestrator.run`), every subsequent call is
    `LLMNodeExecutor.simulate()` for one ready node."""

    def __init__(self, plan_json: str = _PLAN_JSON, node_reply: str = "ok", node_error: Exception = None):
        self._plan_json = plan_json
        self._node_reply = node_reply
        self._node_error = node_error
        self.calls = 0

    async def generate_response(self, prompt, system_instruction, temperature=0.0):
        self.calls += 1
        if self.calls == 1:
            return self._plan_json
        if self._node_error is not None:
            raise self._node_error
        return self._node_reply

    async def generate_stream(self, prompt, system_instruction, temperature=0.0):
        raise NotImplementedError
        yield ""  # pragma: no cover - unreachable, makes this an async generator


def test_submit_task_stream_emits_full_actor_critic_event_sequence(monkeypatch):
    monkeypatch.setattr(
        "src.presentation.routes.tasks.ModelClientFactory.get_client",
        lambda provider_name: _FakeTaskClient(),
    )

    session_id = _create_session()
    response = client.post(
        f"/api/v1/sessions/{session_id}/tasks",
        # Pinned to "llm" -- this test specifically exercises the LLM node
        # executor's actor-critic event sequence/output shape, independent of
        # the route's "sandbox" default (RF-005; see module docstring).
        json={"task": "Align these genes", "execution_mode": "llm"},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]

    events = _parse_sse_events(response.text)
    event_names = [e["event"] for e in events]
    assert event_names == [
        "dag_planned",
        "node_start",
        "node_update",
        "node_start",
        "node_update",
        "review",
        "completed",
    ]

    planned = events[0]
    assert len(planned["nodes"]) == 2
    assert [n["id"] for n in planned["nodes"]] == ["n1", "n2"]

    node_starts = [e for e in events if e["event"] == "node_start"]
    assert [e["node"]["id"] for e in node_starts] == ["n1", "n2"]

    node_updates = [e for e in events if e["event"] == "node_update"]
    assert [e["node"]["status"] for e in node_updates] == ["COMPLETED", "COMPLETED"]
    # The LLM node executor's answer is written onto the node's output.
    assert node_updates[0]["node"]["output"] == {"text": "ok"}

    review = events[5]
    assert review["approved"] is True
    assert review["attempt"] == 1
    assert review["max_attempts"] == 3

    completed = events[6]
    assert completed["session_status"] == "SNAPSHOT_TAKEN"
    assert completed["dag_generation_attempts"] == 1
    assert "nodes" in completed["dag_snapshot"]


@pytest.mark.asyncio
async def test_submit_task_stream_persists_scientific_artifact_on_approval(
    monkeypatch, _isolated_test_database
):
    """RNF-006 gap closure, exercised end-to-end through the real route (not
    just the use case in isolation, see `tests/unit/test_submit_task.py`):
    an approved task run must leave a real `ArtifactModel` row behind, hashed
    against this backend's own `uv.lock`."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.future import select

    from src.domain.services.reproducibility import compute_lockfile_hash, default_lockfile_path
    from src.infrastructure.persistence.models import ArtifactModel

    monkeypatch.setattr(
        "src.presentation.routes.tasks.ModelClientFactory.get_client",
        lambda provider_name: _FakeTaskClient(),
    )

    session_id = _create_session()
    response = client.post(
        f"/api/v1/sessions/{session_id}/tasks",
        json={"task": "Align these genes", "execution_mode": "llm"},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 200

    verify_engine = create_async_engine(_isolated_test_database, future=True)
    verify_sessionmaker = async_sessionmaker(bind=verify_engine, class_=AsyncSession, expire_on_commit=False)
    async with verify_sessionmaker() as db:
        row = (
            await db.execute(
                select(ArtifactModel).filter(ArtifactModel.session_id == UUID(session_id))
            )
        ).scalars().first()
    await verify_engine.dispose()

    assert row is not None
    # The plan's last node is "n2" (see `_PLAN_JSON`), and both are COMPLETED
    # by the LLM node executor -- see `_derive_artifact_name`.
    assert row.name == "n2_output.json"
    assert row.sha256_hash == compute_lockfile_hash(default_lockfile_path())


def test_submit_task_stream_persists_dag_generation_attempts_across_separate_calls(monkeypatch):
    """Confirms the new route benefits from the already-fixed persistence bug
    (see the persistence phase's commit adding the `dag_generation_attempts`
    column to `AgentSessionModel`): the counter accumulates across two
    completely separate HTTP requests to this route for the same session,
    instead of resetting to 0 because a fresh request rebuilds the repository
    from a brand-new DB-backed AsyncSession every time."""
    monkeypatch.setattr(
        "src.presentation.routes.tasks.ModelClientFactory.get_client",
        lambda provider_name: _FakeTaskClient(),
    )

    session_id = _create_session()

    first = client.post(
        f"/api/v1/sessions/{session_id}/tasks",
        json={"task": "Align these genes", "execution_mode": "llm"},
        headers=_AUTH_HEADERS,
    )
    first_completed = [e for e in _parse_sse_events(first.text) if e["event"] == "completed"][0]
    assert first_completed["dag_generation_attempts"] == 1

    second = client.post(
        f"/api/v1/sessions/{session_id}/tasks",
        json={"task": "Align these genes again", "execution_mode": "llm"},
        headers=_AUTH_HEADERS,
    )
    second_completed = [e for e in _parse_sse_events(second.text) if e["event"] == "completed"][0]
    # Not reset to 1 -- picked up the persisted count (1) from the first call
    # and incremented it, proving the counter survives across separate calls.
    assert second_completed["dag_generation_attempts"] == 2


def test_submit_task_stream_unsupported_provider_returns_400():
    session_id = _create_session()
    response = client.post(
        f"/api/v1/sessions/{session_id}/tasks",
        json={"task": "Align these genes", "provider": "not-a-real-provider"},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 400
    assert "Unsupported model provider" in response.json()["detail"]


def test_submit_task_stream_missing_api_key_returns_400(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    session_id = _create_session()
    response = client.post(
        f"/api/v1/sessions/{session_id}/tasks",
        json={"task": "Align these genes", "provider": "deepseek"},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 400
    assert "DEEPSEEK_API_KEY" in response.json()["detail"]


def test_submit_task_stream_nonexistent_session_returns_404():
    response = client.post(
        f"/api/v1/sessions/{uuid4()}/tasks",
        json={"task": "Align these genes"},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 404


def test_submit_task_stream_planner_failure_yields_error_event(monkeypatch):
    # A model that never returns parseable JSON makes LLMTaskPlanner.plan()
    # raise -- the failure happens deep inside the actor-critic loop, after the
    # SSE stream has already opened with a 200, so it must surface as a clean
    # SSE error frame instead of a crashed request (mirrors chat.py's
    # provider-failure test).
    monkeypatch.setattr(
        "src.presentation.routes.tasks.ModelClientFactory.get_client",
        lambda provider_name: _FakeTaskClient(plan_json="I cannot help with that."),
    )

    session_id = _create_session()
    response = client.post(
        f"/api/v1/sessions/{session_id}/tasks",
        json={"task": "Align these genes", "execution_mode": "llm"},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert events[-1]["event"] == "error"
    assert "plan" in events[-1]["message"]


_SANDBOX_PLAN_JSON = json.dumps(
    {
        "nodes": [
            {
                "id": "n1",
                "description": "print a computed number",
                "dependencies": [],
                "language": "bash",
                "command": "echo 42",
            },
        ]
    }
)


def test_submit_task_stream_sandbox_mode_executes_real_commands(monkeypatch):
    """Default `execution_mode` ("sandbox") actually runs the LLM-planned
    `language`/`command` through `SandboxNodeExecutor` + `BubblewrapSandboxDriver`
    instead of asking the model to describe the step -- forced to
    `SANDBOX_RUNTIME=mock` (via the `settings` singleton `get_sandbox_driver`
    reads) so this is deterministic and needs no real `bwrap` binary on the
    test host, mirroring the "config-gated real-vs-mock adapter" pattern used
    everywhere else in this codebase."""
    monkeypatch.setattr(dependencies.settings, "SANDBOX_RUNTIME", "mock")
    monkeypatch.setattr(
        "src.presentation.routes.tasks.ModelClientFactory.get_client",
        lambda provider_name: _FakeTaskClient(plan_json=_SANDBOX_PLAN_JSON),
    )

    session_id = _create_session()
    response = client.post(
        f"/api/v1/sessions/{session_id}/tasks",
        json={"task": "Compute something", "execution_mode": "sandbox"},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 200
    events = _parse_sse_events(response.text)

    node_updates = [e for e in events if e["event"] == "node_update"]
    assert len(node_updates) == 1
    assert node_updates[0]["node"]["status"] == "COMPLETED"
    # Real sandbox execution output shape -- stdout + exit_code, NOT the LLM
    # node executor's `{"text": ...}` shape.
    assert node_updates[0]["node"]["output"] == {
        "stdout": "Mock execution output: 42",
        "exit_code": 0,
    }

    completed = events[-1]
    assert completed["event"] == "completed"
    assert completed["session_status"] == "SNAPSHOT_TAKEN"


def test_submit_task_stream_sandbox_default_without_bwrap_returns_503(monkeypatch):
    """Without an explicit `execution_mode` (defaults to "sandbox") and no
    working `bwrap` on this host, the route must fail loud with a clean 503 --
    never a raw 500, and never a silent unsandboxed fallback (sandboxing is a
    security boundary, see `bubblewrap_driver.py`'s module docstring)."""
    monkeypatch.setattr(bubblewrap_driver.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        "src.presentation.routes.tasks.ModelClientFactory.get_client",
        lambda provider_name: _FakeTaskClient(),
    )

    session_id = _create_session()
    response = client.post(
        f"/api/v1/sessions/{session_id}/tasks",
        json={"task": "Align these genes"},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 503
    assert "bwrap" in response.json()["detail"]
