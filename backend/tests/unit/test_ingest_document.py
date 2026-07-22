"""Unit tests for `IngestDocumentUseCase` (RAG-MARKER write side). All ports
(parser/vector_store/graph_store/model_provider) are faked -- this exercises
the use case's own orchestration logic (parse -> chunk -> upsert -> best-
effort triple extraction), not any concrete adapter. `chunk_fn` is injected
(this use case has zero infrastructure imports of its own, see its module
docstring) -- most tests pass the real `chunk_text` (exercising real
chunking boundaries too), one test injects a fake to exercise the
"produced no chunks" error path deterministically."""
import pytest

from src.application.use_cases.ingest_document import IngestDocumentUseCase
from src.infrastructure.parsing.chunker import chunk_text


class _FakeParser:
    def __init__(self, text):
        self._text = text

    async def parse(self, pdf_bytes):
        return self._text


class _FailingParser:
    async def parse(self, pdf_bytes):
        raise RuntimeError("corrupt pdf")


class _RecordingVectorStore:
    def __init__(self):
        self.upserted = []

    async def search(self, query, top_k=5):
        return []

    async def upsert(self, chunks):
        self.upserted.append(chunks)


class _RecordingGraphStore:
    def __init__(self):
        self.triples = []

    async def get_relations(self, subject):
        return []

    async def add_triple(self, subject, predicate, object_entity):
        self.triples.append((subject, predicate, object_entity))


class _FakeModelProvider:
    def __init__(self, response):
        self._response = response

    async def generate_response(self, prompt, system_instruction, temperature=0.0):
        return self._response

    def generate_stream(self, prompt, system_instruction, temperature=0.0):  # pragma: no cover
        raise NotImplementedError


class _BoomModelProvider:
    async def generate_response(self, prompt, system_instruction, temperature=0.0):
        raise RuntimeError("provider down")

    def generate_stream(self, prompt, system_instruction, temperature=0.0):  # pragma: no cover
        raise NotImplementedError


_LONG_TEXT = (
    "TP53 is a tumor suppressor gene that regulates the cell cycle. "
    "It is one of the most frequently mutated genes in human cancer. "
    "CRISPR-Cas9 enables precise genome editing in eukaryotic cells. "
    "The technology has revolutionized functional genomics research."
)


@pytest.mark.asyncio
async def test_execute_parses_chunks_and_upserts_into_vector_store():
    vector_store = _RecordingVectorStore()
    use_case = IngestDocumentUseCase(
        parser=_FakeParser(_LONG_TEXT),
        chunk_fn=chunk_text,
        vector_store=vector_store,
    )

    chunks_indexed = await use_case.execute(document_id="doc1", pdf_bytes=b"irrelevant")

    assert chunks_indexed >= 1
    assert len(vector_store.upserted) == 1
    upserted_chunks = vector_store.upserted[0]
    assert len(upserted_chunks) == chunks_indexed
    for i, chunk in enumerate(upserted_chunks):
        assert chunk["id"] == f"doc1:{i}"
        assert chunk["metadata"]["document_id"] == "doc1"
        assert chunk["metadata"]["chunk_index"] == i
        assert "text" in chunk


@pytest.mark.asyncio
async def test_execute_includes_filename_in_metadata_when_given():
    vector_store = _RecordingVectorStore()
    use_case = IngestDocumentUseCase(
        parser=_FakeParser(_LONG_TEXT), chunk_fn=chunk_text, vector_store=vector_store
    )

    await use_case.execute(document_id="doc1", pdf_bytes=b"x", filename="paper.pdf")

    assert vector_store.upserted[0][0]["metadata"]["filename"] == "paper.pdf"


@pytest.mark.asyncio
async def test_execute_omits_filename_key_when_not_given():
    vector_store = _RecordingVectorStore()
    use_case = IngestDocumentUseCase(
        parser=_FakeParser(_LONG_TEXT), chunk_fn=chunk_text, vector_store=vector_store
    )

    await use_case.execute(document_id="doc1", pdf_bytes=b"x")

    assert "filename" not in vector_store.upserted[0][0]["metadata"]


@pytest.mark.asyncio
async def test_execute_raises_value_error_on_empty_parsed_text():
    use_case = IngestDocumentUseCase(
        parser=_FakeParser("   "), chunk_fn=chunk_text, vector_store=_RecordingVectorStore()
    )

    with pytest.raises(ValueError, match="no extractable text"):
        await use_case.execute(document_id="doc1", pdf_bytes=b"x")


@pytest.mark.asyncio
async def test_execute_propagates_parser_failure():
    use_case = IngestDocumentUseCase(
        parser=_FailingParser(), chunk_fn=chunk_text, vector_store=_RecordingVectorStore()
    )

    with pytest.raises(RuntimeError, match="corrupt pdf"):
        await use_case.execute(document_id="doc1", pdf_bytes=b"x")


@pytest.mark.asyncio
async def test_execute_skips_graph_enrichment_when_graph_store_or_model_provider_missing():
    vector_store = _RecordingVectorStore()
    graph_store = _RecordingGraphStore()

    # graph_store given but no model_provider -- must not attempt enrichment.
    use_case = IngestDocumentUseCase(
        parser=_FakeParser(_LONG_TEXT),
        chunk_fn=chunk_text,
        vector_store=vector_store,
        graph_store=graph_store,
    )
    await use_case.execute(document_id="doc1", pdf_bytes=b"x")

    assert graph_store.triples == []


@pytest.mark.asyncio
async def test_execute_extracts_triples_when_both_graph_store_and_model_provider_given():
    vector_store = _RecordingVectorStore()
    graph_store = _RecordingGraphStore()
    model_provider = _FakeModelProvider(
        '{"triples": [{"subject": "TP53", "predicate": "regulates", "object": "cell cycle"}]}'
    )

    use_case = IngestDocumentUseCase(
        parser=_FakeParser(_LONG_TEXT),
        chunk_fn=chunk_text,
        vector_store=vector_store,
        graph_store=graph_store,
        model_provider=model_provider,
    )
    await use_case.execute(document_id="doc1", pdf_bytes=b"x")

    assert graph_store.triples == [("TP53", "regulates", "cell cycle")]


@pytest.mark.asyncio
async def test_execute_ignores_malformed_triples_in_response():
    vector_store = _RecordingVectorStore()
    graph_store = _RecordingGraphStore()
    model_provider = _FakeModelProvider(
        '{"triples": [{"subject": "TP53"}, "not a dict", '
        '{"subject": "A", "predicate": "b", "object": "C"}]}'
    )

    use_case = IngestDocumentUseCase(
        parser=_FakeParser(_LONG_TEXT),
        chunk_fn=chunk_text,
        vector_store=vector_store,
        graph_store=graph_store,
        model_provider=model_provider,
    )
    await use_case.execute(document_id="doc1", pdf_bytes=b"x")

    assert graph_store.triples == [("A", "b", "C")]


@pytest.mark.asyncio
async def test_execute_succeeds_even_when_triple_extraction_llm_call_fails():
    vector_store = _RecordingVectorStore()
    graph_store = _RecordingGraphStore()
    use_case = IngestDocumentUseCase(
        parser=_FakeParser(_LONG_TEXT),
        chunk_fn=chunk_text,
        vector_store=vector_store,
        graph_store=graph_store,
        model_provider=_BoomModelProvider(),
    )

    chunks_indexed = await use_case.execute(document_id="doc1", pdf_bytes=b"x")

    assert chunks_indexed >= 1
    assert vector_store.upserted  # vector upsert still happened
    assert graph_store.triples == []  # best-effort enrichment silently failed


@pytest.mark.asyncio
async def test_execute_succeeds_even_when_triple_extraction_returns_unparseable_json():
    vector_store = _RecordingVectorStore()
    graph_store = _RecordingGraphStore()
    model_provider = _FakeModelProvider("I cannot extract anything from this.")
    use_case = IngestDocumentUseCase(
        parser=_FakeParser(_LONG_TEXT),
        chunk_fn=chunk_text,
        vector_store=vector_store,
        graph_store=graph_store,
        model_provider=model_provider,
    )

    chunks_indexed = await use_case.execute(document_id="doc1", pdf_bytes=b"x")

    assert chunks_indexed >= 1
    assert graph_store.triples == []


@pytest.mark.asyncio
async def test_execute_raises_value_error_when_text_produces_no_chunks():
    use_case = IngestDocumentUseCase(
        parser=_FakeParser(_LONG_TEXT),
        chunk_fn=lambda text: [],
        vector_store=_RecordingVectorStore(),
    )

    with pytest.raises(ValueError, match="could not be split"):
        await use_case.execute(document_id="doc1", pdf_bytes=b"x")
