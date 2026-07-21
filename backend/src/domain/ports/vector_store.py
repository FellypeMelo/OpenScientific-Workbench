from typing import Any, Dict, List, Protocol


class VectorStorePort(Protocol):
    """Semantic retrieval + indexing over ingested document chunks (RAG-MARKER)."""

    async def search(self, query: str, top_k: int = 5) -> List[str]:
        """Return up to ``top_k`` passage texts most relevant to ``query``."""
        ...

    async def upsert(self, chunks: List[Dict[str, Any]]) -> None:
        """Embed and store ``chunks`` for later ``search``.

        Each dict must carry a ``"text"`` key (the passage to embed and
        return from ``search``). An optional ``"id"`` (any hashable,
        human-readable identifier -- NOT required to be a UUID/int itself;
        implementations are responsible for deriving a store-compliant point
        id from it) and an optional ``"metadata"`` dict (extra payload
        fields, e.g. ``document_id``/``chunk_index``) may also be present.
        """
        ...
