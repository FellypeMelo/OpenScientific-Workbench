"""Document ingestion pipeline (RAG-MARKER): parse -> chunk -> embed/upsert
each chunk into the vector store, then best-effort extract knowledge-graph
triples from the parsed text via the already-wired LLM (`ModelProviderPort`).

This is the WRITE side of GraphRAG; `RetrieveContextUseCase` (see
`retrieve_context.py`) is the READ side. Only depends on domain ports/services,
per this codebase's Clean Architecture layering -- the concrete parser
(pypdf/Marker) and Qdrant/Neo4j adapters are all injected by the caller
(`presentation/routes/documents.py`).

`chunk_fn` (the paragraph/sentence-boundary chunker,
`infrastructure/parsing/chunker.py::chunk_text`) is ALSO injected rather than
imported directly here, even though it is a pure, zero-I/O function with no
adapter/port of its own -- this use case (application layer) must not import
from `infrastructure/` at all, so the presentation layer wires the concrete
function in at construction time, exactly like it wires the parser/
vector_store/graph_store ports.
"""
import logging
from typing import Callable, List, Optional

from src.domain.ports.document_parser import DocumentParserPort
from src.domain.ports.graph_store import GraphStorePort
from src.domain.ports.model_provider import ModelProviderPort
from src.domain.ports.vector_store import VectorStorePort
from src.domain.services.json_extraction import extract_json

logger = logging.getLogger(__name__)

_TRIPLE_EXTRACTION_INSTRUCTION = (
    "You are a biomedical knowledge-graph extraction assistant. Given a "
    "passage of scientific text, extract factual subject-predicate-object "
    "triples about biological/chemical entities (genes, proteins, diseases, "
    "compounds, pathways). Respond with ONLY a JSON object of the form "
    '{"triples": [{"subject": "...", "predicate": "...", "object": "..."}]}. '
    'If no clear triples are present, respond with {"triples": []}. Do not '
    "include any prose outside the JSON."
)

# Caps how much parsed text is sent to the LLM for triple extraction, keeping
# a single ingestion call's token/cost bounded regardless of document length.
# The vector store still indexes the FULL document via chunking below --
# only graph-triple extraction is capped, since it is a best-effort
# enrichment step, not the primary deliverable of this use case.
_MAX_EXTRACTION_CHARS = 8000


class IngestDocumentUseCase:
    def __init__(
        self,
        parser: DocumentParserPort,
        chunk_fn: Callable[[str], List[str]],
        vector_store: VectorStorePort,
        graph_store: Optional[GraphStorePort] = None,
        model_provider: Optional[ModelProviderPort] = None,
    ):
        self.parser = parser
        self.chunk_fn = chunk_fn
        self.vector_store = vector_store
        self.graph_store = graph_store
        self.model_provider = model_provider

    async def execute(self, document_id: str, pdf_bytes: bytes, filename: Optional[str] = None) -> int:
        """Parses ``pdf_bytes``, chunks + embeds + upserts the result into the
        vector store, and (if both a graph store and a model provider were
        given) best-effort extracts graph triples. Returns the number of
        chunks indexed.

        Raises ``ValueError`` if the document contains no extractable text or
        the extracted text could not be split into any chunk -- both are
        genuine "this upload was not ingestible" outcomes the caller (route)
        should surface as a 422, not silently swallow.
        """
        text = await self.parser.parse(pdf_bytes)
        if not text or not text.strip():
            raise ValueError("Parsed document contained no extractable text.")

        chunks = self.chunk_fn(text)
        if not chunks:
            raise ValueError("Document text could not be split into any chunk.")

        await self.vector_store.upsert(
            [
                {
                    "id": f"{document_id}:{i}",
                    "text": chunk,
                    "metadata": {
                        "document_id": document_id,
                        "chunk_index": i,
                        **({"filename": filename} if filename else {}),
                    },
                }
                for i, chunk in enumerate(chunks)
            ]
        )

        if self.graph_store is not None and self.model_provider is not None:
            await self._extract_triples_best_effort(document_id, text)

        return len(chunks)

    async def _extract_triples_best_effort(self, document_id: str, text: str) -> None:
        excerpt = text[:_MAX_EXTRACTION_CHARS]
        try:
            raw = await self.model_provider.generate_response(
                prompt=excerpt,
                system_instruction=_TRIPLE_EXTRACTION_INSTRUCTION,
                temperature=0.0,
            )
            payload = extract_json(raw)
            triples = payload.get("triples") if isinstance(payload, dict) else None
            if not isinstance(triples, list):
                return
            for triple in triples:
                if not isinstance(triple, dict):
                    continue
                subject = triple.get("subject")
                predicate = triple.get("predicate")
                obj = triple.get("object")
                if subject and predicate and obj:
                    await self.graph_store.add_triple(str(subject), str(predicate), str(obj))
        except Exception:
            # Best-effort: a triple-extraction failure (LLM error, malformed
            # JSON, provider hiccup) must never fail the ingestion -- the
            # vector-store upsert above already succeeded and is the primary
            # deliverable of this use case.
            logger.warning(
                "Best-effort triple extraction failed for document_id=%s; "
                "continuing without graph enrichment.",
                document_id,
                exc_info=True,
            )
