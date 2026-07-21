import json

import pytest
from fastapi.testclient import TestClient
from uuid import UUID, uuid4
from src.presentation.main import app
from src.presentation.middleware.jwt_auth import create_access_token

client = TestClient(app)

# All application routes now require a valid `Authorization: Bearer <token>` header
# (Fase 2 - JWT auth middleware applies globally). Mint one via the helper the
# middleware itself exposes for exactly this purpose (there is no login endpoint
# yet -- see `presentation/middleware/jwt_auth.py` module docstring).
_AUTH_HEADERS = {"Authorization": f"Bearer {create_access_token(uuid4(), iam_role='scientist')}"}


def _create_session() -> str:
    """
    Creates a real session (via the actual route, persisted through the real
    repository stack) owned by `_AUTH_HEADERS`'s authenticated caller, and
    returns its id.

    Needed because `POST /sessions/{id}/chat` now looks up the session and
    checks its owning workspace before doing anything else (IDOR fix, see
    `routes/chat.py`) -- a bare `uuid4()` session id that was never created no
    longer reaches the streaming logic at all, it just 404s.
    """
    response = client.post(
        "/api/v1/sessions",
        json={"workspace_id": str(uuid4())},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 201
    return response.json()["id"]


def _parse_sse_events(body: str):
    """Parse a `text/event-stream` body into the list of `{"event", "message"}`
    dicts emitted by `routes/chat.py`'s `_sse` helper (one per `data: ` line)."""
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


class _FakeStreamingClient:
    """Stand-in for a real `ModelProviderPort` implementation: yields a fixed
    sequence of text deltas from `generate_stream` without making any network
    call, so chat-route tests stay fast and deterministic."""

    def __init__(self, deltas):
        self._deltas = deltas

    async def generate_response(self, prompt: str, system_instruction: str, temperature: float = 0.0) -> str:
        return "".join(self._deltas)

    async def generate_stream(self, prompt: str, system_instruction: str, temperature: float = 0.0):
        for delta in self._deltas:
            yield delta


def test_create_session_endpoint():
    workspace_id = str(uuid4())

    # This will fail initially (RED) because app/routes are not fully mounted
    # or the dependencies are not mocked.
    response = client.post(
        "/api/v1/sessions",
        json={"workspace_id": workspace_id},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["session_status"] == "INITIALIZING"


def test_chat_streaming_endpoint(monkeypatch):
    # Mock the LLM client at the factory boundary so this test never makes a
    # real network call regardless of which provider API keys happen to be
    # set in the environment (see test_model_providers.py, which sets/leaves
    # DEEPSEEK_API_KEY etc. in os.environ for the process lifetime).
    monkeypatch.setattr(
        "src.presentation.routes.chat.ModelClientFactory.get_client",
        lambda provider_name: _FakeStreamingClient(["Hello", " ", "world"]),
    )

    session_id = _create_session()
    response = client.post(
        f"/api/v1/sessions/{session_id}/chat",
        json={"prompt": "Test query"},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 200
    # Assert it returns a streaming connection (SSE)
    assert "text/event-stream" in response.headers["content-type"]

    events = _parse_sse_events(response.text)
    assert events[0] == {"event": "planning", "message": "Initiating MCTS agent loop..."}
    # Accumulated (not per-delta) text on each "executing" frame.
    assert [e["message"] for e in events if e["event"] == "executing"] == [
        "Hello",
        "Hello ",
        "Hello world",
    ]
    assert events[-1] == {"event": "completed", "message": "Hello world"}


def test_chat_streaming_endpoint_unsupported_provider_returns_400():
    session_id = _create_session()
    response = client.post(
        f"/api/v1/sessions/{session_id}/chat",
        json={"prompt": "Test query", "provider": "not-a-real-provider"},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 400
    assert "Unsupported model provider" in response.json()["detail"]


def test_chat_streaming_endpoint_missing_api_key_returns_400(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    session_id = _create_session()
    response = client.post(
        f"/api/v1/sessions/{session_id}/chat",
        json={"prompt": "Test query", "provider": "deepseek"},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 400
    assert "DEEPSEEK_API_KEY" in response.json()["detail"]


def test_chat_streaming_endpoint_nonexistent_session_returns_404():
    response = client.post(
        f"/api/v1/sessions/{uuid4()}/chat",
        json={"prompt": "Test query"},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 404


def test_chat_streaming_endpoint_provider_failure_yields_error_event(monkeypatch):
    class _BoomClient:
        async def generate_response(self, prompt, system_instruction, temperature=0.0):
            raise RuntimeError("boom")

        async def generate_stream(self, prompt, system_instruction, temperature=0.0):
            raise RuntimeError("boom")
            yield ""  # pragma: no cover - unreachable, makes this an async generator

    monkeypatch.setattr(
        "src.presentation.routes.chat.ModelClientFactory.get_client",
        lambda provider_name: _BoomClient(),
    )

    session_id = _create_session()
    response = client.post(
        f"/api/v1/sessions/{session_id}/chat",
        json={"prompt": "Test query"},
        headers=_AUTH_HEADERS,
    )
    # The HTTP status is already committed (200) by the time the provider
    # fails mid-stream; the failure must surface as a clean SSE error frame
    # instead of a crash.
    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert events[-1]["event"] == "error"


async def _fetch_session_row(db_url: str, session_id: str):
    """Query the raw `AgentSessionModel` row through a fresh engine/session
    bound to the isolated test SQLite file, mirroring
    `tests/integration/test_routes_with_db.py`'s "verify via a brand new
    engine against the same db_url" pattern -- proves the assertion reads back
    what was actually persisted, not some in-process cached object."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.future import select
    from src.infrastructure.persistence.models import AgentSessionModel

    verify_engine = create_async_engine(db_url, future=True)
    verify_sessionmaker = async_sessionmaker(
        bind=verify_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with verify_sessionmaker() as db:
        row = (
            await db.execute(
                select(AgentSessionModel).filter(AgentSessionModel.id == UUID(session_id))
            )
        ).scalars().first()
    await verify_engine.dispose()
    return row


@pytest.mark.asyncio
async def test_chat_streaming_endpoint_sanitizes_pii_and_appends_provenance(
    monkeypatch, _isolated_test_database
):
    """RNF-005 (LGPD/GDPR): a successful chat turn must append a provenance_log
    entry whose logged/persisted prompt has PII masked -- while the ORIGINAL,
    unsanitized prompt is still what actually reaches the LLM (see
    `routes/chat.py`'s reasoning comment for why sanitizing the LLM-bound copy
    too would break legitimate requests)."""
    captured_prompts = []

    class _CapturingClient(_FakeStreamingClient):
        async def generate_stream(self, prompt: str, system_instruction: str, temperature: float = 0.0):
            captured_prompts.append(prompt)
            async for delta in super().generate_stream(prompt, system_instruction, temperature):
                yield delta

    monkeypatch.setattr(
        "src.presentation.routes.chat.ModelClientFactory.get_client",
        lambda provider_name: _CapturingClient(["Hello"]),
    )

    session_id = _create_session()
    raw_prompt = "Please contact me at researcher@osw.org about this run."
    response = client.post(
        f"/api/v1/sessions/{session_id}/chat",
        json={"prompt": raw_prompt},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 200
    _parse_sse_events(response.text)  # drain the stream

    # The real LLM call received the original, unsanitized prompt.
    assert captured_prompts == [raw_prompt]

    row = await _fetch_session_row(_isolated_test_database, session_id)
    assert row is not None
    entry = row.provenance_log[-1]
    assert entry["action"] == "chat_message"
    assert entry["provider"] == "deepseek"
    assert entry["status"] == "success"
    assert "researcher@osw.org" not in entry["prompt"]
    assert "[EMAIL_MASKED]" in entry["prompt"]


@pytest.mark.asyncio
async def test_chat_streaming_endpoint_provider_failure_appends_error_provenance(
    monkeypatch, _isolated_test_database
):
    class _BoomClient:
        async def generate_response(self, prompt, system_instruction, temperature=0.0):
            raise RuntimeError("boom")

        async def generate_stream(self, prompt, system_instruction, temperature=0.0):
            raise RuntimeError("boom")
            yield ""  # pragma: no cover - unreachable, makes this an async generator

    monkeypatch.setattr(
        "src.presentation.routes.chat.ModelClientFactory.get_client",
        lambda provider_name: _BoomClient(),
    )

    session_id = _create_session()
    raw_prompt = "CPF 123.456.789-00 lookup"
    response = client.post(
        f"/api/v1/sessions/{session_id}/chat",
        json={"prompt": raw_prompt},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 200

    row = await _fetch_session_row(_isolated_test_database, session_id)
    assert row is not None
    entry = row.provenance_log[-1]
    assert entry["action"] == "chat_message"
    assert entry["status"] == "error"
    assert "123.456.789-00" not in entry["prompt"]
    assert "[CPF_MASKED]" in entry["prompt"]
