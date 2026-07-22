"""Proteomics/pharmacology DB adapters (query_pride/query_gtopdb/blast_sequence),
tested against httpx's built-in `MockTransport` (same pattern
`test_bio_direct_adapters.py` uses) so no real network call/external mock
server is needed while still exercising the real HTTP request/response
handling logic."""
from urllib.parse import parse_qs

import httpx
import pytest

from src.infrastructure.mcp.proteomics_pharma_db_adapters import (
    ProteomicsPharmaAPIError,
    ProteomicsPharmaDBAdapters,
    register_proteomics_pharma_db_tools,
)
from src.infrastructure.mcp.server_registry import MCPServerRegistry


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _blast_adapters(client, max_poll_attempts=3):
    # Poll interval driven to 0 so tests never actually sleep; a small,
    # explicit attempt budget lets the timeout path be exercised quickly too.
    return ProteomicsPharmaDBAdapters(
        client, blast_poll_interval_seconds=0, blast_max_poll_attempts=max_poll_attempts
    )


# --- query_pride -------------------------------------------------------


@pytest.mark.asyncio
async def test_query_pride_accession_success_returns_project_dict():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"accession": "PXD000001", "title": "TMT spike-in", "projectDescription": "..."},
        )

    client = _client(handler)
    adapters = ProteomicsPharmaDBAdapters(client)

    result = await adapters.query_pride({"accession": "PXD000001"})

    assert result["accession"] == "PXD000001"
    assert captured["url"] == "https://www.ebi.ac.uk/pride/ws/archive/v2/projects/PXD000001"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_pride_missing_args_raises_value_error():
    adapters = ProteomicsPharmaDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'accession'"):
        await adapters.query_pride({})

    with pytest.raises(ValueError, match="non-empty 'accession'"):
        await adapters.query_pride(None)


@pytest.mark.asyncio
async def test_query_pride_accession_404_raises_api_error():
    client = _client(lambda r: httpx.Response(404, json={"error": "not found"}))
    adapters = ProteomicsPharmaDBAdapters(client)

    with pytest.raises(ProteomicsPharmaAPIError, match="was not found"):
        await adapters.query_pride({"accession": "PXD999999"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_pride_accession_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = ProteomicsPharmaDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_pride({"accession": "PXD000001"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_pride_accession_malformed_body_raises_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = ProteomicsPharmaDBAdapters(client)

    with pytest.raises(ProteomicsPharmaAPIError, match="expected project data"):
        await adapters.query_pride({"accession": "PXD000001"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_pride_keyword_success_returns_list():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=[{"accession": "PXD000001", "title": "cancer study"}])

    client = _client(handler)
    adapters = ProteomicsPharmaDBAdapters(client)

    result = await adapters.query_pride({"keyword": "cancer"})

    assert result == [{"accession": "PXD000001", "title": "cancer study"}]
    assert captured["url"].startswith("https://www.ebi.ac.uk/pride/ws/archive/v2/search/projects")
    assert captured["params"]["keyword"] == "cancer"
    assert captured["params"]["pageSize"] == "10"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_pride_keyword_non_list_response_raises_api_error():
    client = _client(lambda r: httpx.Response(200, json={"error": "malformed"}))
    adapters = ProteomicsPharmaDBAdapters(client)

    with pytest.raises(ProteomicsPharmaAPIError, match="unexpected response shape"):
        await adapters.query_pride({"keyword": "cancer"})
    await client.aclose()


# --- query_gtopdb --------------------------------------------------------


@pytest.mark.asyncio
async def test_query_gtopdb_id_lookup_success_returns_target_dict():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"targetId": 1797, "name": "epidermal growth factor receptor"})

    client = _client(handler)
    adapters = ProteomicsPharmaDBAdapters(client)

    result = await adapters.query_gtopdb({"object_type": "target", "id": 1797})

    assert result["targetId"] == 1797
    assert captured["url"] == "https://www.guidetopharmacology.org/services/targets/1797"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_gtopdb_name_search_success_returns_list():
    captured = {}

    def handler(request):
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=[{"ligandId": 407, "name": "aspirin"}])

    client = _client(handler)
    adapters = ProteomicsPharmaDBAdapters(client)

    result = await adapters.query_gtopdb({"object_type": "ligand", "name": "aspirin"})

    assert result == [{"ligandId": 407, "name": "aspirin"}]
    assert captured["params"]["name"] == "aspirin"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_gtopdb_missing_object_type_raises_value_error():
    adapters = ProteomicsPharmaDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="'object_type'"):
        await adapters.query_gtopdb({"name": "EGFR"})


@pytest.mark.asyncio
async def test_query_gtopdb_invalid_object_type_raises_value_error():
    adapters = ProteomicsPharmaDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="'object_type'"):
        await adapters.query_gtopdb({"object_type": "compound", "name": "EGFR"})


@pytest.mark.asyncio
async def test_query_gtopdb_missing_id_and_name_raises_value_error():
    adapters = ProteomicsPharmaDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'id'"):
        await adapters.query_gtopdb({"object_type": "target"})


@pytest.mark.asyncio
async def test_query_gtopdb_id_lookup_404_raises_api_error():
    client = _client(lambda r: httpx.Response(404, text="not found"))
    adapters = ProteomicsPharmaDBAdapters(client)

    with pytest.raises(ProteomicsPharmaAPIError, match="was not found"):
        await adapters.query_gtopdb({"object_type": "target", "id": 999999})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_gtopdb_id_lookup_204_raises_api_error():
    client = _client(lambda r: httpx.Response(204))
    adapters = ProteomicsPharmaDBAdapters(client)

    with pytest.raises(ProteomicsPharmaAPIError, match="was not found"):
        await adapters.query_gtopdb({"object_type": "ligand", "id": 999999})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_gtopdb_name_search_204_returns_empty_list():
    client = _client(lambda r: httpx.Response(204))
    adapters = ProteomicsPharmaDBAdapters(client)

    result = await adapters.query_gtopdb({"object_type": "target", "name": "nonexistent-xyz"})

    assert result == []
    await client.aclose()


@pytest.mark.asyncio
async def test_query_gtopdb_id_lookup_malformed_body_raises_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = ProteomicsPharmaDBAdapters(client)

    with pytest.raises(ProteomicsPharmaAPIError, match="expected data"):
        await adapters.query_gtopdb({"object_type": "target", "id": 1797})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_gtopdb_name_search_non_list_response_raises_api_error():
    client = _client(lambda r: httpx.Response(200, json={"error": "malformed"}))
    adapters = ProteomicsPharmaDBAdapters(client)

    with pytest.raises(ProteomicsPharmaAPIError, match="unexpected response shape"):
        await adapters.query_gtopdb({"object_type": "target", "name": "EGFR"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_gtopdb_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = ProteomicsPharmaDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_gtopdb({"object_type": "target", "name": "EGFR"})
    await client.aclose()


# --- blast_sequence --------------------------------------------------------


@pytest.mark.asyncio
async def test_blast_sequence_success_submits_polls_and_returns_tabular_result():
    calls = []

    def handler(request):
        calls.append(request)
        params = dict(request.url.params)
        if request.method == "POST":
            body = parse_qs(request.content.decode())
            assert body["CMD"] == ["Put"]
            assert body["PROGRAM"] == ["blastn"]
            assert body["DATABASE"] == ["core_nt"]
            assert body["QUERY"] == ["ACGTACGTACGT"]
            return httpx.Response(
                200, text="<!--QBlastInfoBegin\n  RID = TEST123\n  RTOE = 5\nQBlastInfoEnd\n-->"
            )
        if params.get("FORMAT_OBJECT") == "SearchInfo":
            assert params["RID"] == "TEST123"
            return httpx.Response(200, text="QBlastInfoBegin\n  Status=READY\n  ThereAreHits=yes\nQBlastInfoEnd")
        assert params["CMD"] == "Get"
        assert params["RID"] == "TEST123"
        assert params["FORMAT_TYPE"] == "Text"
        return httpx.Response(200, text="query\tsubject\tidentity\nQ1\tS1\t99.0\n")

    client = _client(handler)
    adapters = _blast_adapters(client)

    result = await adapters.blast_sequence({"sequence": "ACGTACGTACGT"})

    assert result["rid"] == "TEST123"
    assert result["program"] == "blastn"
    assert result["database"] == "core_nt"
    assert "Q1" in result["content"]
    # Put (POST) + one status poll (GET) + one result fetch (GET) == 3 calls.
    assert len(calls) == 3
    await client.aclose()


@pytest.mark.asyncio
async def test_blast_sequence_missing_sequence_raises_value_error():
    adapters = _blast_adapters(_client(lambda r: httpx.Response(200, text="")))

    with pytest.raises(ValueError, match="non-empty 'sequence'"):
        await adapters.blast_sequence({})

    with pytest.raises(ValueError, match="non-empty 'sequence'"):
        await adapters.blast_sequence(None)


@pytest.mark.asyncio
async def test_blast_sequence_invalid_program_raises_value_error():
    adapters = _blast_adapters(_client(lambda r: httpx.Response(200, text="")))

    with pytest.raises(ValueError, match="'program' must be one of"):
        await adapters.blast_sequence({"sequence": "ACGT", "program": "bogusblast"})


@pytest.mark.asyncio
async def test_blast_sequence_put_without_rid_raises_api_error():
    client = _client(lambda r: httpx.Response(200, text="<html>no rid here</html>"))
    adapters = _blast_adapters(client)

    with pytest.raises(ProteomicsPharmaAPIError, match="did not return a request ID"):
        await adapters.blast_sequence({"sequence": "ACGT"})
    await client.aclose()


@pytest.mark.asyncio
async def test_blast_sequence_status_failed_raises_api_error():
    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, text="RID = FAILRID\nRTOE = 1")
        return httpx.Response(200, text="Status=FAILED")

    client = _client(handler)
    adapters = _blast_adapters(client)

    with pytest.raises(ProteomicsPharmaAPIError, match="failed on the server side"):
        await adapters.blast_sequence({"sequence": "ACGT"})
    await client.aclose()


@pytest.mark.asyncio
async def test_blast_sequence_status_unknown_raises_api_error():
    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, text="RID = OLDRID\nRTOE = 1")
        return httpx.Response(200, text="Status=UNKNOWN")

    client = _client(handler)
    adapters = _blast_adapters(client)

    with pytest.raises(ProteomicsPharmaAPIError, match="RID may have expired"):
        await adapters.blast_sequence({"sequence": "ACGT"})
    await client.aclose()


@pytest.mark.asyncio
async def test_blast_sequence_poll_timeout_raises_api_error():
    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, text="RID = SLOWRID\nRTOE = 1")
        return httpx.Response(200, text="Status=WAITING")

    client = _client(handler)
    adapters = _blast_adapters(client, max_poll_attempts=2)

    with pytest.raises(ProteomicsPharmaAPIError, match="did not complete within the polling budget"):
        await adapters.blast_sequence({"sequence": "ACGT"})
    await client.aclose()


@pytest.mark.asyncio
async def test_blast_sequence_empty_result_raises_api_error():
    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, text="RID = EMPTYRID\nRTOE = 1")
        params = dict(request.url.params)
        if params.get("FORMAT_OBJECT") == "SearchInfo":
            return httpx.Response(200, text="Status=READY")
        return httpx.Response(200, text="   ")

    client = _client(handler)
    adapters = _blast_adapters(client)

    with pytest.raises(ProteomicsPharmaAPIError, match="empty result"):
        await adapters.blast_sequence({"sequence": "ACGT"})
    await client.aclose()


@pytest.mark.asyncio
async def test_blast_sequence_upstream_500_on_submit_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = _blast_adapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.blast_sequence({"sequence": "ACGT"})
    await client.aclose()


# --- register_proteomics_pharma_db_tools -----------------------------------


@pytest.mark.asyncio
async def test_register_proteomics_pharma_db_tools_makes_all_three_tools_routable(monkeypatch):
    # `register_proteomics_pharma_db_tools` always builds its adapter with the
    # module's real (multi-second) `BLAST_POLL_INTERVAL_SECONDS` default, since
    # it takes no poll-tuning knobs of its own. Patch `asyncio.sleep` (rather
    # than the constant, which is only read once at class-definition time as a
    # default-argument value) so this test still exercises the real
    # `register_*`/`route()` path without actually sleeping.
    import asyncio

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    def handler(request):
        url = str(request.url)
        if "pride" in url:
            return httpx.Response(200, json={"accession": "PXD000001", "title": "demo"})
        if "guidetopharmacology" in url:
            return httpx.Response(200, json={"targetId": 1, "name": "demo target"})
        if "blast.ncbi.nlm.nih.gov" in url:
            if request.method == "POST":
                return httpx.Response(200, text="RID = REGRID\nRTOE = 1")
            params = dict(request.url.params)
            if params.get("FORMAT_OBJECT") == "SearchInfo":
                return httpx.Response(200, text="Status=READY")
            return httpx.Response(200, text="hit table content")
        return httpx.Response(500)

    client = _client(handler)
    registry = MCPServerRegistry()

    registered = register_proteomics_pharma_db_tools(registry, client)

    assert set(registered) == {"query_pride", "query_gtopdb", "blast_sequence"}
    assert set(registered).issubset(registry.registry.keys())

    pride_out = await registry.route("query_pride", {"accession": "PXD000001"})
    assert "PXD000001" in pride_out

    gtopdb_out = await registry.route("query_gtopdb", {"object_type": "target", "id": 1})
    assert "demo target" in gtopdb_out

    # Registered via the default constructor (no poll-interval override), so
    # force a fast poll here by monkeypatching asyncio.sleep is unnecessary --
    # the mock handler above returns READY on the very first poll, so only
    # `BLAST_POLL_INTERVAL_SECONDS` worth of sleep (a few seconds) happens
    # once. Kept short (module default) rather than mocked away, matching how
    # `register_direct_bio_tools`' own tests avoid over-mocking internals.
    blast_out = await registry.route("blast_sequence", {"sequence": "ACGT"})
    assert "hit table content" in blast_out

    await client.aclose()


@pytest.mark.asyncio
async def test_register_proteomics_pharma_db_tools_without_injected_client_uses_default_names():
    # No client injected -> ProteomicsPharmaDBAdapters would build a real
    # httpx.AsyncClient per call. We only assert registration here (no real
    # network call is made in this test), matching how `bio_direct_adapters.py`'s
    # own registration-only tests work.
    registry = MCPServerRegistry()

    registered = register_proteomics_pharma_db_tools(registry)

    assert set(registered) == {"query_pride", "query_gtopdb", "blast_sequence"}
