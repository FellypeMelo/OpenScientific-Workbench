"""Real-path tests for `QdrantVectorStore` (RAG-MARKER). `AsyncQdrantClient`
is mocked at the transport boundary (the class itself, same convention as
`test_neo4j_client_real.py` mocks `AsyncGraphDatabase`) so these tests
exercise the *real* collection-bootstrap / point-shape / query-shape logic
without requiring a live Qdrant server or a real FastEmbed model download,
neither of which exist in this sandbox during a plain `pytest` run.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from qdrant_client import models

from src.infrastructure.vector import qdrant_client as qdrant_client_module
from src.infrastructure.vector.qdrant_client import QdrantVectorStore


def _make_fake_client(collection_exists=False, query_points_result=None):
    client = MagicMock(name="async_qdrant_client")
    client.collection_exists = AsyncMock(return_value=collection_exists)
    client.create_collection = AsyncMock(return_value=True)
    client.get_fastembed_vector_params = MagicMock(
        return_value={"fast-bge-small-en": models.VectorParams(size=384, distance=models.Distance.COSINE)}
    )
    client.get_vector_field_name = MagicMock(return_value="fast-bge-small-en")
    client.upsert = AsyncMock(return_value=None)
    client.query_points = AsyncMock(return_value=query_points_result or MagicMock(points=[]))
    client.close = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_real_upsert_creates_missing_collection_and_upserts_named_vector(monkeypatch):
    fake_client = _make_fake_client(collection_exists=False)
    monkeypatch.setattr(
        qdrant_client_module, "AsyncQdrantClient", MagicMock(return_value=fake_client)
    )

    store = QdrantVectorStore(collection="osw_documents", enabled=True)
    await store.upsert(
        [
            {"id": "doc1:0", "text": "TP53 regulates the cell cycle.", "metadata": {"document_id": "doc1"}},
        ]
    )

    fake_client.collection_exists.assert_awaited_once_with("osw_documents")
    fake_client.create_collection.assert_awaited_once()
    _, create_kwargs = fake_client.create_collection.call_args
    assert create_kwargs["collection_name"] == "osw_documents"

    fake_client.upsert.assert_awaited_once()
    _, upsert_kwargs = fake_client.upsert.call_args
    assert upsert_kwargs["collection_name"] == "osw_documents"
    points = upsert_kwargs["points"]
    assert len(points) == 1
    point = points[0]
    # Point id must be a valid UUID string, never the raw human-readable id.
    assert point.id != "doc1:0"
    import uuid as uuid_module

    uuid_module.UUID(point.id)  # raises ValueError if not a valid UUID
    # Named-vector shape: keyed by the collection's actual vector field name.
    assert "fast-bge-small-en" in point.vector
    assert isinstance(point.vector["fast-bge-small-en"], models.Document)
    assert point.vector["fast-bge-small-en"].text == "TP53 regulates the cell cycle."
    # Readable identifier preserved in the payload, not lost.
    assert point.payload["chunk_id"] == "doc1:0"
    assert point.payload["document_id"] == "doc1"
    assert point.payload["text"] == "TP53 regulates the cell cycle."


@pytest.mark.asyncio
async def test_real_upsert_reuses_existing_collection_without_recreating(monkeypatch):
    fake_client = _make_fake_client(collection_exists=True)
    monkeypatch.setattr(
        qdrant_client_module, "AsyncQdrantClient", MagicMock(return_value=fake_client)
    )

    store = QdrantVectorStore(enabled=True)
    await store.upsert([{"id": "a", "text": "x"}])
    await store.upsert([{"id": "b", "text": "y"}])

    fake_client.create_collection.assert_not_awaited()
    # `collection_exists` checked once, then cached (`_collection_ready`).
    fake_client.collection_exists.assert_awaited_once()


@pytest.mark.asyncio
async def test_real_upsert_generates_random_id_when_no_id_given(monkeypatch):
    fake_client = _make_fake_client(collection_exists=True)
    monkeypatch.setattr(
        qdrant_client_module, "AsyncQdrantClient", MagicMock(return_value=fake_client)
    )

    store = QdrantVectorStore(enabled=True)
    await store.upsert([{"text": "no id here"}])

    _, upsert_kwargs = fake_client.upsert.call_args
    point = upsert_kwargs["points"][0]
    import uuid as uuid_module

    uuid_module.UUID(point.id)
    assert "chunk_id" not in point.payload


@pytest.mark.asyncio
async def test_real_upsert_noop_on_empty_chunk_list(monkeypatch):
    fake_client = _make_fake_client()
    monkeypatch.setattr(
        qdrant_client_module, "AsyncQdrantClient", MagicMock(return_value=fake_client)
    )

    store = QdrantVectorStore(enabled=True)
    await store.upsert([])

    fake_client.upsert.assert_not_awaited()
    fake_client.collection_exists.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_search_returns_empty_when_collection_missing(monkeypatch):
    fake_client = _make_fake_client(collection_exists=False)
    monkeypatch.setattr(
        qdrant_client_module, "AsyncQdrantClient", MagicMock(return_value=fake_client)
    )

    store = QdrantVectorStore(enabled=True)
    results = await store.search("what regulates the cell cycle?")

    assert results == []
    fake_client.query_points.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_search_queries_with_document_and_returns_payload_text(monkeypatch):
    hit = MagicMock()
    hit.payload = {"text": "TP53 regulates the cell cycle.", "chunk_id": "doc1:0"}
    fake_client = _make_fake_client(
        collection_exists=True, query_points_result=MagicMock(points=[hit])
    )
    monkeypatch.setattr(
        qdrant_client_module, "AsyncQdrantClient", MagicMock(return_value=fake_client)
    )

    store = QdrantVectorStore(collection="osw_documents", enabled=True)
    results = await store.search("cell cycle regulation", top_k=3)

    assert results == ["TP53 regulates the cell cycle."]
    fake_client.query_points.assert_awaited_once()
    _, query_kwargs = fake_client.query_points.call_args
    assert query_kwargs["collection_name"] == "osw_documents"
    assert isinstance(query_kwargs["query"], models.Document)
    assert query_kwargs["query"].text == "cell cycle regulation"
    assert query_kwargs["using"] == "fast-bge-small-en"
    assert query_kwargs["limit"] == 3


@pytest.mark.asyncio
async def test_real_search_skips_hits_with_no_payload_text(monkeypatch):
    hit_with_text = MagicMock()
    hit_with_text.payload = {"text": "kept"}
    hit_without_payload = MagicMock()
    hit_without_payload.payload = None
    hit_empty_text = MagicMock()
    hit_empty_text.payload = {"text": ""}

    fake_client = _make_fake_client(
        collection_exists=True,
        query_points_result=MagicMock(points=[hit_with_text, hit_without_payload, hit_empty_text]),
    )
    monkeypatch.setattr(
        qdrant_client_module, "AsyncQdrantClient", MagicMock(return_value=fake_client)
    )

    store = QdrantVectorStore(enabled=True)
    results = await store.search("query")

    assert results == ["kept"]


@pytest.mark.asyncio
async def test_client_created_once_and_reused_across_calls(monkeypatch):
    fake_client = _make_fake_client(collection_exists=True)
    constructor = MagicMock(return_value=fake_client)
    monkeypatch.setattr(qdrant_client_module, "AsyncQdrantClient", constructor)

    store = QdrantVectorStore(enabled=True)
    await store.search("q1")
    await store.search("q2")

    constructor.assert_called_once()


@pytest.mark.asyncio
async def test_close_closes_real_client(monkeypatch):
    fake_client = _make_fake_client(collection_exists=True)
    monkeypatch.setattr(
        qdrant_client_module, "AsyncQdrantClient", MagicMock(return_value=fake_client)
    )

    store = QdrantVectorStore(enabled=True)
    await store.search("q")
    await store.close()

    fake_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_is_noop_when_never_connected():
    store = QdrantVectorStore(enabled=False)
    await store.close()  # must not raise


@pytest.mark.asyncio
async def test_mock_mode_upsert_and_search_round_trip():
    store = QdrantVectorStore(enabled=False)

    await store.upsert([{"id": "a", "text": "hello"}])
    assert store._mock_store == [{"id": "a", "text": "hello"}]

    results = await store.search("hello", top_k=5)
    assert len(results) == 1
    assert "mock retrieval chunk" in results[0]


@pytest.mark.asyncio
async def test_enabled_defaults_to_settings_qdrant_enabled(monkeypatch):
    monkeypatch.setattr(qdrant_client_module.settings, "QDRANT_ENABLED", False)
    store = QdrantVectorStore()
    assert store._is_mock is True

    monkeypatch.setattr(qdrant_client_module.settings, "QDRANT_ENABLED", True)
    store = QdrantVectorStore()
    assert store._is_mock is False
