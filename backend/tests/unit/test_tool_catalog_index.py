"""Unit tests for `ToolCatalogIndex` (retrieval-based tool selection for
`LLMTaskPlanner`, see `infrastructure/llm/tool_catalog_index.py`)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from qdrant_client import models

from src.infrastructure.llm.tool_catalog_index import (
    ToolCatalogIndex,
    load_catalog_descriptions,
    parse_tool_descriptions,
)
from src.infrastructure.vector import qdrant_client as qdrant_client_module
from src.infrastructure.vector.qdrant_client import QdrantVectorStore


def _make_fake_qdrant_client():
    client = MagicMock(name="async_qdrant_client")
    client.collection_exists = AsyncMock(return_value=False)
    client.create_collection = AsyncMock(return_value=True)
    client.get_fastembed_vector_params = MagicMock(
        return_value={"fast-bge-small-en": models.VectorParams(size=384, distance=models.Distance.COSINE)}
    )
    client.get_vector_field_name = MagicMock(return_value="fast-bge-small-en")
    client.upsert = AsyncMock(return_value=None)
    client.query_points = AsyncMock(return_value=MagicMock(points=[]))
    client.close = AsyncMock()
    return client


class _FakeStore:
    """Minimal `QdrantVectorStore`-shaped double, so `ToolCatalogIndex`'s OWN
    parsing/formatting logic can be tested without re-exercising the real
    store's embedding plumbing (already covered by `test_qdrant_client_real.py`)."""

    def __init__(self, enabled=True, search_results=None):
        self.enabled = enabled
        self.upserted = None
        self._search_results = search_results or []

    async def upsert(self, chunks):
        self.upserted = chunks

    async def search(self, query, top_k=5):
        self.last_query = query
        self.last_top_k = top_k
        return self._search_results


def test_parse_tool_descriptions_extracts_bare_and_parametrized_entries():
    text = (
        "- **query_uniprot** — Query UniProt REST API (NL or direct endpoint).\n"
        "- **pcr_simple**(sequence: str, forward_primer: str) — simulate PCR amplification.\n"
        "- not a catalog line\n"
    )

    descriptions = parse_tool_descriptions(text)

    assert descriptions["query_uniprot"] == "Query UniProt REST API (NL or direct endpoint)."
    assert descriptions["pcr_simple"] == "simulate PCR amplification."
    assert len(descriptions) == 2


def test_parse_tool_descriptions_handles_nested_parens_in_signature():
    """A tuple default like `time_span: tuple = (0,24)` closes a naive
    `[^)]*` signature group early, dropping the whole entry -- regression
    test for that (see action_tool_catalog.md's simulate_thyroid_hormone_
    pharmacokinetics / simulate_whole_cell_ode_model entries)."""
    text = (
        "- **simulate_thyroid_hormone_pharmacokinetics**(patient_data: dict, "
        "time_span: tuple = (0,24), dose: float = 0) — ODE-based thyroid hormone PK.\n"
    )

    descriptions = parse_tool_descriptions(text)

    assert descriptions["simulate_thyroid_hormone_pharmacokinetics"] == "ODE-based thyroid hormone PK."


def test_parse_tool_descriptions_first_occurrence_wins_across_multiple_texts():
    first = "- **query_uniprot** — first description.\n"
    second = "- **query_uniprot** — second description.\n"

    descriptions = parse_tool_descriptions(first, second)

    assert descriptions["query_uniprot"] == "first description."


def test_load_catalog_descriptions_reads_real_catalog_docs():
    descriptions = load_catalog_descriptions()

    assert "query_uniprot" in descriptions
    assert "pcr_simple" in descriptions
    # Nested-paren-in-signature regression (see
    # test_parse_tool_descriptions_handles_nested_parens_in_signature).
    assert "simulate_thyroid_hormone_pharmacokinetics" in descriptions
    assert "simulate_whole_cell_ode_model" in descriptions
    assert len(descriptions) > 100


def test_usable_reflects_store_enabled_flag():
    assert ToolCatalogIndex(QdrantVectorStore(enabled=True)).usable is True
    assert ToolCatalogIndex(QdrantVectorStore(enabled=False)).usable is False


@pytest.mark.asyncio
async def test_ensure_indexed_noop_when_not_usable():
    store = _FakeStore(enabled=False)
    index = ToolCatalogIndex(store)

    await index.ensure_indexed(["query_uniprot"], {"query_uniprot": "desc"})

    assert store.upserted is None


@pytest.mark.asyncio
async def test_ensure_indexed_noop_on_empty_tool_names():
    store = _FakeStore(enabled=True)
    index = ToolCatalogIndex(store)

    await index.ensure_indexed([], {})

    assert store.upserted is None


@pytest.mark.asyncio
async def test_ensure_indexed_upserts_name_and_description_encoded_together():
    store = _FakeStore(enabled=True)
    index = ToolCatalogIndex(store)

    await index.ensure_indexed(
        ["query_uniprot", "no_description_tool"], {"query_uniprot": "Query UniProt."}
    )

    assert store.upserted == [
        {"id": "query_uniprot", "text": "query_uniprot::Query UniProt."},
        # Falls back to the bare name when no description was parsed for it.
        {"id": "no_description_tool", "text": "no_description_tool::no_description_tool"},
    ]


@pytest.mark.asyncio
async def test_ensure_indexed_is_idempotent_within_a_process():
    store = _FakeStore(enabled=True)
    index = ToolCatalogIndex(store)

    await index.ensure_indexed(["a"], {})
    store.upserted = None  # reset the spy
    await index.ensure_indexed(["a", "b"], {})

    assert store.upserted is None  # second call was a no-op, never re-upserted


@pytest.mark.asyncio
async def test_top_k_empty_when_not_usable():
    index = ToolCatalogIndex(_FakeStore(enabled=False, search_results=["a::desc"]))

    assert await index.top_k("do something", 5) == []


@pytest.mark.asyncio
async def test_top_k_parses_name_and_description_pairs():
    store = _FakeStore(
        enabled=True,
        search_results=["query_uniprot::Query UniProt.", "pcr_simple::simulate PCR amplification."],
    )
    index = ToolCatalogIndex(store)

    results = await index.top_k("fetch a protein sequence", 5)

    assert results == [
        ("query_uniprot", "Query UniProt."),
        ("pcr_simple", "simulate PCR amplification."),
    ]
    assert store.last_query == "fetch a protein sequence"
    assert store.last_top_k == 5


@pytest.mark.asyncio
async def test_top_k_skips_malformed_entries_without_separator():
    store = _FakeStore(enabled=True, search_results=["not_indexed_by_this_class", "ok::fine"])
    index = ToolCatalogIndex(store)

    results = await index.top_k("q", 5)

    assert results == [("ok", "fine")]


@pytest.mark.asyncio
async def test_close_closes_underlying_store(monkeypatch):
    fake_client = _make_fake_qdrant_client()
    monkeypatch.setattr(
        qdrant_client_module, "AsyncQdrantClient", MagicMock(return_value=fake_client)
    )
    store = QdrantVectorStore(enabled=True)
    await store.search("warm up the client")
    index = ToolCatalogIndex(store)

    await index.close()

    fake_client.close.assert_awaited_once()
