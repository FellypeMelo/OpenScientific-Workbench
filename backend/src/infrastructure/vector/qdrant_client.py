"""Qdrant vector-store adapter (RAG-MARKER).

Real semantic search via a lazily-constructed `AsyncQdrantClient` talking to
an actual Qdrant instance (see `docker-compose.yml`'s `qdrant` service),
using its built-in FastEmbed local-inference support: both indexed chunks and
search queries are passed as `models.Document(text=..., model=...)` and
embedded on-the-fly (ONNX weights downloaded once, on first use, into the
local FastEmbed cache) -- no separate embedding service/model-serving
infrastructure needed. Verified against the installed `qdrant-client==1.18.0`
API (current docs via Context7, https://context7.com/qdrant/qdrant-client):
`query_points(..., query=models.Document(...))` is the supported entry point,
NOT the deprecated `AsyncQdrantFastembedMixin.query()`/`.add()` convenience
wrappers.

Falls back to a deterministic in-memory mock whenever `settings.QDRANT_ENABLED`
is `False` -- mirrors the same "real infra not configured" gating pattern
`Neo4jGraphClient`/`VaultClient` use, so a fresh checkout / CI unit-test run
with no live Qdrant instance still boots and stays deterministic. Unlike
those two, Qdrant is normal always-on infra in this architecture (not
optional), so `QDRANT_ENABLED` defaults to `True` rather than gating on
credential presence.

Design notes specific to this adapter:
- `create_collection` is called with `vectors_config=client.get_fastembed_vector_params()`,
  which yields a NAMED vector field (e.g. `"fast-bge-small-en"`), not the
  single unnamed vector shape most Qdrant examples show. Every `upsert`/
  `query_points` call must therefore address that same field name
  (`client.get_vector_field_name()`) explicitly -- confirmed empirically
  against a real (local-mode) Qdrant instance: omitting it raises
  `ValueError: Unnamed vectors are not allowed when a collection has named
  vectors...`.
- Point ids: Qdrant only accepts an unsigned int or a UUID as a point id
  (https://qdrant.tech/documentation/concepts/points/#point-ids) -- a
  human-readable chunk identifier (e.g. `"<document_id>:<chunk_index>"`) is
  therefore never used AS the point id. Instead it is hashed, deterministically,
  into a UUID via `uuid.uuid5` (so re-ingesting the same document/chunk
  upserts/overwrites the same point rather than duplicating it), and the
  original readable identifier is preserved verbatim in the payload under
  `"chunk_id"`.
"""
import logging
import uuid
from typing import Any, Dict, List, Optional

from qdrant_client import AsyncQdrantClient, models

from src.infrastructure.config import settings

logger = logging.getLogger(__name__)

# FastEmbed's default local-inference model (`AsyncQdrantClient.DEFAULT_EMBEDDING_MODEL`):
# BAAI/bge-small-en, a 384-dim sentence embedding model, ~130MB of ONNX
# weights downloaded once on first real use. Deliberately not overridable via
# settings (yet) -- keeping ingestion and query embeddings on the exact same
# model is a correctness requirement (mixed-model vectors are not
# meaningfully comparable), so this is a single, explicit constant both
# `upsert` and `search` below reference.
_EMBEDDING_MODEL = AsyncQdrantClient.DEFAULT_EMBEDDING_MODEL


class QdrantVectorStore:
    def __init__(
        self,
        collection: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        enabled: Optional[bool] = None,
    ):
        self.collection = collection or settings.QDRANT_COLLECTION
        self.host = host or settings.QDRANT_HOST
        self.port = port if port is not None else settings.QDRANT_PORT
        # Explicit `is None` check (not `or`) so callers/tests can force the
        # mock path with `enabled=False` regardless of `settings.QDRANT_ENABLED`,
        # mirroring `Neo4jGraphClient`'s `password=""` override convention.
        self.enabled = settings.QDRANT_ENABLED if enabled is None else enabled
        self._client: Optional[AsyncQdrantClient] = None
        self._collection_ready = False
        # Mock-mode in-memory store, mirrors `Neo4jGraphClient._mock_db`, so
        # `upsert()` + `search()` are round-trippable in tests/CI without a
        # real Qdrant instance. Not vector-searched (no embedding happens in
        # mock mode) -- `search()` still returns the same deterministic
        # placeholder chunks it always has, this list just makes `upsert()`
        # a real (not silently-discarding) no-op.
        self._mock_store: List[Dict[str, Any]] = []

    @property
    def _is_mock(self) -> bool:
        return not self.enabled

    def _get_client(self) -> AsyncQdrantClient:
        if self._client is None:
            self._client = AsyncQdrantClient(host=self.host, port=self.port)
        return self._client

    async def _ensure_collection(self, client: AsyncQdrantClient) -> None:
        if self._collection_ready:
            return
        if not await client.collection_exists(self.collection):
            await client.create_collection(
                collection_name=self.collection,
                vectors_config=client.get_fastembed_vector_params(),
            )
        self._collection_ready = True

    async def upsert(self, chunks: List[Dict[str, Any]]) -> None:
        """Embeds and stores each chunk (see `VectorStorePort.upsert`)."""
        if not chunks:
            return
        if self._is_mock:
            self._mock_store.extend(chunks)
            return

        client = self._get_client()
        await self._ensure_collection(client)
        vector_field = client.get_vector_field_name()

        points = []
        for chunk in chunks:
            text = chunk["text"]
            raw_id = chunk.get("id")
            point_id = (
                str(uuid.uuid5(uuid.NAMESPACE_URL, str(raw_id)))
                if raw_id is not None
                else str(uuid.uuid4())
            )
            payload: Dict[str, Any] = dict(chunk.get("metadata") or {})
            payload["text"] = text
            if raw_id is not None:
                payload.setdefault("chunk_id", str(raw_id))
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector={vector_field: models.Document(text=text, model=_EMBEDDING_MODEL)},
                    payload=payload,
                )
            )

        await client.upsert(collection_name=self.collection, points=points)

    async def search(self, query: str, top_k: int = 5) -> List[str]:
        if self._is_mock:
            count = max(1, min(top_k, 1))
            return [f"[mock retrieval chunk {i + 1} for {query!r}]" for i in range(count)]

        client = self._get_client()
        if not await client.collection_exists(self.collection):
            # Nothing has been ingested yet -- empty context is the correct,
            # expected answer, not an error.
            return []
        self._collection_ready = True

        response = await client.query_points(
            collection_name=self.collection,
            query=models.Document(text=query, model=_EMBEDDING_MODEL),
            using=client.get_vector_field_name(),
            limit=top_k,
        )
        return [point.payload["text"] for point in response.points if point.payload and point.payload.get("text")]

    async def close(self) -> None:
        """Releases the real client's connection pool, if one was created.
        Wired into `presentation/main.py`'s `lifespan` shutdown."""
        if self._client is not None:
            await self._client.close()
            self._client = None
