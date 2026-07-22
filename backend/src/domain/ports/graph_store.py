from typing import Any, Dict, List, Protocol


class GraphStorePort(Protocol):
    """Knowledge-graph reads + writes for GraphRAG (RAG-MARKER).

    Implemented by ``Neo4jGraphClient``; injected into both the READ side
    (``RetrieveContextUseCase``, via ``get_relations``) and the WRITE side
    (``IngestDocumentUseCase``'s best-effort triple extraction, via
    ``add_triple``) so each depends on this interface, not the concrete
    driver.

    ``add_triple`` was originally missing from this Protocol even though
    ``IngestDocumentUseCase`` (added in the RAG-MARKER ingestion phase) has
    always called it on its injected ``graph_store`` -- every real/test
    implementation (``Neo4jGraphClient``, and every ``graph_store`` test
    double in ``tests/unit/test_ingest_document.py`` /
    ``test_documents_route.py``) already provided it, so nothing broke at
    runtime, but the port's declared contract didn't match its actual usage
    (confirmed with `mypy`: `Item "GraphStorePort" of "GraphStorePort | None"
    has no attribute "add_triple"`). Declared here now so the port fully
    describes what callers actually depend on.
    """

    async def get_relations(self, subject: str) -> List[Dict[str, Any]]:
        """Returns every ``{"subject", "predicate", "object"}`` triple whose
        ``subject`` matches, for GraphRAG context retrieval."""
        ...

    async def add_triple(self, subject: str, predicate: str, object_entity: str) -> None:
        """Persists one biological RDF-style triple (subject-predicate-object)
        into the graph store, for best-effort knowledge-graph enrichment
        during document ingestion."""
        ...
