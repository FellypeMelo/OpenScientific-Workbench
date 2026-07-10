from typing import List, Protocol


class VectorStorePort(Protocol):
    """Semantic retrieval over ingested document chunks (RAG-MARKER)."""

    async def search(self, query: str, top_k: int = 5) -> List[str]:
        """Return up to ``top_k`` passage texts most relevant to ``query``."""
        ...
