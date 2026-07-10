"""Graph + vector context assembly for RAG (RAG-MARKER).

Combines knowledge-graph relations (GraphStorePort) and retrieved passages
(VectorStorePort) into a single context block an LLM can be grounded on. Both
collaborators are ports, so the use case is fully mockable.
"""
from src.domain.ports.graph_store import GraphStorePort
from src.domain.ports.vector_store import VectorStorePort


class RetrieveContextUseCase:
    def __init__(self, graph_store: GraphStorePort, vector_store: VectorStorePort):
        self.graph_store = graph_store
        self.vector_store = vector_store

    async def execute(self, query: str, top_k: int = 5, entity: str = None) -> str:
        subject = entity or query
        relations = await self.graph_store.get_relations(subject)
        chunks = await self.vector_store.search(query, top_k)

        sections = []
        if relations:
            graph_lines = "\n".join(
                f"- {r['subject']} {r['predicate']} {r['object']}" for r in relations
            )
            sections.append(f"## Knowledge Graph\n{graph_lines}")
        if chunks:
            sections.append("## Retrieved Passages\n" + "\n".join(f"- {c}" for c in chunks))

        return "\n\n".join(sections)
