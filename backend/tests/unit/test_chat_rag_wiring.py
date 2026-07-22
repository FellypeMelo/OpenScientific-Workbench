"""RAG-MARKER: `POST /sessions/{id}/chat` must fold `RetrieveContextUseCase`'s
result into the system instruction handed to the BYOK provider, and must
degrade gracefully (never 500, never abort the chat turn) when the vector/
graph store raise -- see `routes/chat.py`'s wiring."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.presentation.dependencies import get_graph_store, get_vector_store
from src.presentation.main import app
from src.presentation.middleware.jwt_auth import create_access_token

client = TestClient(app)

_AUTH_HEADERS = {"Authorization": f"Bearer {create_access_token(uuid4(), iam_role='scientist')}"}


def _create_session() -> str:
    response = client.post(
        "/api/v1/sessions",
        json={"workspace_id": str(uuid4())},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 201
    return response.json()["id"]


class _CapturingClient:
    """Records the `system_instruction` it was actually driven with, so tests
    can assert on the RAG-folded prompt without a real provider call."""

    def __init__(self, deltas):
        self._deltas = deltas
        self.system_instructions: list[str] = []

    async def generate_response(self, prompt, system_instruction, temperature=0.0):
        self.system_instructions.append(system_instruction)
        return "".join(self._deltas)

    async def generate_stream(self, prompt, system_instruction, temperature=0.0):
        self.system_instructions.append(system_instruction)
        for delta in self._deltas:
            yield delta


class _FakeGraphStore:
    def __init__(self, relations=None, error=None):
        self._relations = relations or []
        self._error = error

    async def get_relations(self, subject):
        if self._error:
            raise self._error
        return self._relations


class _FakeVectorStore:
    def __init__(self, chunks=None, error=None):
        self._chunks = chunks or []
        self._error = error

    async def search(self, query, top_k=5):
        if self._error:
            raise self._error
        return self._chunks

    async def upsert(self, chunks):
        return None


@pytest.fixture(autouse=True)
def _clear_rag_overrides():
    # Each test in this module sets its own overrides explicitly; make sure
    # none leak into a later test/module.
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_graph_store, None)
        app.dependency_overrides.pop(get_vector_store, None)


def test_chat_folds_retrieved_context_into_system_instruction(monkeypatch):
    fake_client = _CapturingClient(["ok"])
    monkeypatch.setattr(
        "src.presentation.routes.chat.ModelClientFactory.get_client",
        lambda provider_name: fake_client,
    )
    app.dependency_overrides[get_graph_store] = lambda: _FakeGraphStore(
        relations=[{"subject": "TP53", "predicate": "interacts_with", "object": "MDM2"}]
    )
    app.dependency_overrides[get_vector_store] = lambda: _FakeVectorStore(
        chunks=["TP53 regulates apoptosis (Nature 2021)."]
    )

    session_id = _create_session()
    response = client.post(
        f"/api/v1/sessions/{session_id}/chat",
        json={"prompt": "Tell me about TP53"},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert len(fake_client.system_instructions) == 1
    instruction = fake_client.system_instructions[0]
    assert "interacts_with" in instruction and "MDM2" in instruction
    assert "regulates apoptosis" in instruction


def test_chat_stays_ungrounded_when_context_is_empty(monkeypatch):
    fake_client = _CapturingClient(["ok"])
    monkeypatch.setattr(
        "src.presentation.routes.chat.ModelClientFactory.get_client",
        lambda provider_name: fake_client,
    )
    app.dependency_overrides[get_graph_store] = lambda: _FakeGraphStore()
    app.dependency_overrides[get_vector_store] = lambda: _FakeVectorStore()

    session_id = _create_session()
    response = client.post(
        f"/api/v1/sessions/{session_id}/chat",
        json={"prompt": "Anything?"},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 200
    from src.presentation.routes.chat import DEFAULT_SYSTEM_INSTRUCTION

    assert fake_client.system_instructions == [DEFAULT_SYSTEM_INSTRUCTION]


def test_chat_degrades_gracefully_when_vector_store_raises(monkeypatch):
    fake_client = _CapturingClient(["ok"])
    monkeypatch.setattr(
        "src.presentation.routes.chat.ModelClientFactory.get_client",
        lambda provider_name: fake_client,
    )
    app.dependency_overrides[get_graph_store] = lambda: _FakeGraphStore()
    app.dependency_overrides[get_vector_store] = lambda: _FakeVectorStore(
        error=ConnectionError("qdrant unreachable")
    )

    session_id = _create_session()
    response = client.post(
        f"/api/v1/sessions/{session_id}/chat",
        json={"prompt": "Tell me about TP53"},
        headers=_AUTH_HEADERS,
    )

    # No 500: the retrieval failure must be swallowed, not propagated.
    assert response.status_code == 200
    from src.presentation.routes.chat import DEFAULT_SYSTEM_INSTRUCTION

    assert fake_client.system_instructions == [DEFAULT_SYSTEM_INSTRUCTION]
    events = [
        line for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert any('"event": "completed"' in line for line in events)


def test_chat_degrades_gracefully_when_graph_store_raises(monkeypatch):
    fake_client = _CapturingClient(["ok"])
    monkeypatch.setattr(
        "src.presentation.routes.chat.ModelClientFactory.get_client",
        lambda provider_name: fake_client,
    )
    app.dependency_overrides[get_graph_store] = lambda: _FakeGraphStore(
        error=RuntimeError("neo4j unreachable")
    )
    app.dependency_overrides[get_vector_store] = lambda: _FakeVectorStore()

    session_id = _create_session()
    response = client.post(
        f"/api/v1/sessions/{session_id}/chat",
        json={"prompt": "Tell me about TP53"},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 200
    from src.presentation.routes.chat import DEFAULT_SYSTEM_INSTRUCTION

    assert fake_client.system_instructions == [DEFAULT_SYSTEM_INSTRUCTION]
