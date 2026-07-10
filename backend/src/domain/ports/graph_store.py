from typing import Any, Dict, List, Protocol


class GraphStorePort(Protocol):
    """Knowledge-graph reads for GraphRAG (RAG-MARKER).

    Implemented by Neo4jGraphClient; injected into the retrieval use case so it
    depends on the interface, not the concrete driver.
    """

    async def get_relations(self, subject: str) -> List[Dict[str, Any]]:
        ...
