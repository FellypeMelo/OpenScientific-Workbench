"""Unit tests for `POST /api/v1/documents/ingest` (RAG-MARKER ingestion
route). The parser/vector-store/graph-store ports are overridden via the
standard `app.dependency_overrides` pattern (same as every other route test
in this suite); `ModelClientFactory.get_client` is monkeypatched at the
module boundary (same convention `test_presentation_routes.py`'s chat tests
use) so no real BYOK network call happens.
"""
import io
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.infrastructure.config import settings
from src.presentation.dependencies import (
    get_document_parser,
    get_graph_store,
    get_vector_store,
)
from src.presentation.main import app
from src.presentation.middleware.jwt_auth import create_access_token
from tests.unit._pdf_fixtures import build_minimal_pdf

client = TestClient(app)

_AUTH_HEADERS = {"Authorization": f"Bearer {create_access_token(uuid4(), iam_role='scientist')}"}


class _FakeParser:
    def __init__(self, text="TP53 is a tumor suppressor gene. It regulates the cell cycle.", error=None):
        self._text = text
        self._error = error

    async def parse(self, pdf_bytes):
        if self._error:
            raise self._error
        return self._text


class _RecordingVectorStore:
    def __init__(self):
        self.upserted = []

    async def search(self, query, top_k=5):
        return []

    async def upsert(self, chunks):
        self.upserted.append(chunks)


class _RecordingGraphStore:
    def __init__(self):
        self.triples = []

    async def get_relations(self, subject):
        return []

    async def add_triple(self, subject, predicate, object_entity):
        self.triples.append((subject, predicate, object_entity))


class _FakeModelClient:
    async def generate_response(self, prompt, system_instruction, temperature=0.0):
        return '{"triples": []}'

    async def generate_stream(self, prompt, system_instruction, temperature=0.0):  # pragma: no cover
        yield ""


@pytest.fixture(autouse=True)
def _override_ports():
    parser = _FakeParser()
    vector_store = _RecordingVectorStore()
    graph_store = _RecordingGraphStore()
    app.dependency_overrides[get_document_parser] = lambda: parser
    app.dependency_overrides[get_vector_store] = lambda: vector_store
    app.dependency_overrides[get_graph_store] = lambda: graph_store
    try:
        yield {"parser": parser, "vector_store": vector_store, "graph_store": graph_store}
    finally:
        app.dependency_overrides.pop(get_document_parser, None)
        app.dependency_overrides.pop(get_vector_store, None)
        app.dependency_overrides.pop(get_graph_store, None)


def test_ingest_document_requires_auth():
    response = client.post(
        "/api/v1/documents/ingest",
        files={"file": ("paper.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
    )
    assert response.status_code == 401


def test_ingest_document_success_indexes_chunks_and_returns_document_id(monkeypatch, _override_ports):
    monkeypatch.setattr(
        "src.presentation.routes.documents.ModelClientFactory.get_client",
        lambda provider_name: _FakeModelClient(),
    )
    pdf_bytes = build_minimal_pdf("TP53 regulates the cell cycle.")

    response = client.post(
        "/api/v1/documents/ingest",
        files={"file": ("paper.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "paper.pdf"
    assert body["chunks_indexed"] >= 1
    import uuid as uuid_module

    uuid_module.UUID(body["document_id"])  # a real UUID was generated

    assert len(_override_ports["vector_store"].upserted) == 1


def test_ingest_document_sanitizes_path_traversal_filename(monkeypatch, _override_ports):
    monkeypatch.setattr(
        "src.presentation.routes.documents.ModelClientFactory.get_client",
        lambda provider_name: _FakeModelClient(),
    )
    response = client.post(
        "/api/v1/documents/ingest",
        files={"file": ("../../evil.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 201
    assert response.json()["filename"] == "evil.pdf"


def test_ingest_document_empty_upload_returns_400(_override_ports):
    response = client.post(
        "/api/v1/documents/ingest",
        files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_ingest_document_over_size_cap_returns_413(monkeypatch, _override_ports):
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 1)
    oversized = b"x" * (2 * 1024 * 1024)

    response = client.post(
        "/api/v1/documents/ingest",
        files={"file": ("big.pdf", io.BytesIO(oversized), "application/pdf")},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 413


def test_ingest_document_unparseable_pdf_returns_422(_override_ports):
    app.dependency_overrides[get_document_parser] = lambda: _FakeParser(text="   ")

    response = client.post(
        "/api/v1/documents/ingest",
        files={"file": ("blank.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 422


def test_ingest_document_missing_api_key_still_ingests_vector_only(monkeypatch, _override_ports):
    # No `ModelClientFactory.get_client` monkeypatch here -- the real factory
    # raises `ValueError` for a provider with no configured API key. The
    # route must degrade to vector-only indexing (201), not fail the whole
    # ingestion over an optional enrichment step.
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    response = client.post(
        "/api/v1/documents/ingest",
        files={"file": ("paper.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 201
    assert response.json()["chunks_indexed"] >= 1
    assert _override_ports["graph_store"].triples == []
