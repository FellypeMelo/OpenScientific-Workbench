"""RAG-MARKER: RetrieveContextUseCase merges graph relations and vector chunks
into one grounding context. Both ports are faked."""
import pytest

from src.application.use_cases.retrieve_context import RetrieveContextUseCase
from src.infrastructure.vector.qdrant_client import QdrantVectorStore
from src.infrastructure.graph.neo4j_client import Neo4jGraphClient


class FakeGraph:
    async def get_relations(self, subject):
        return [{"subject": subject, "predicate": "interacts_with", "object": "MDM2"}]


class FakeVector:
    async def search(self, query, top_k=5):
        return ["TP53 regulates apoptosis (Nature 2021)."]


class EmptyGraph:
    async def get_relations(self, subject):
        return []


@pytest.mark.asyncio
async def test_context_combines_graph_and_vector_text():
    use_case = RetrieveContextUseCase(FakeGraph(), FakeVector())

    context = await use_case.execute("TP53")

    assert "interacts_with" in context and "MDM2" in context
    assert "regulates apoptosis" in context
    assert "Knowledge Graph" in context and "Retrieved Passages" in context


@pytest.mark.asyncio
async def test_context_omits_empty_graph_section():
    use_case = RetrieveContextUseCase(EmptyGraph(), FakeVector())

    context = await use_case.execute("TP53")

    assert "Knowledge Graph" not in context
    assert "Retrieved Passages" in context


@pytest.mark.asyncio
async def test_use_case_works_with_real_adapter_shapes():
    # Neo4jGraphClient (mock path) + QdrantVectorStore (mock path) satisfy the ports.
    graph = Neo4jGraphClient(uri="bolt://mock", password="")
    await graph.add_triple("TP53", "interacts_with", "MDM2")

    context = await RetrieveContextUseCase(graph, QdrantVectorStore()).execute("TP53")

    assert "MDM2" in context
    assert "mock retrieval chunk" in context
