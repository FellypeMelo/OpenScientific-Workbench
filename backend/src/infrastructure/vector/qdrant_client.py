"""Qdrant vector-store adapter (RAG-MARKER).

Real semantic search needs an embedding model to vectorise the query plus a
running Qdrant instance populated by the Marker PDF-ingestion pipeline
(torch/surya-ocr) -- all infra-blocked here. Until that exists this returns a
deterministic mock chunk so the retrieval use case is exercisable end-to-end.
"""
from typing import List


class QdrantVectorStore:
    def __init__(self, collection: str = "osw_papers"):
        self.collection = collection

    async def search(self, query: str, top_k: int = 5) -> List[str]:
        count = max(1, min(top_k, 1))
        return [f"[mock retrieval chunk {i + 1} for {query!r}]" for i in range(count)]
