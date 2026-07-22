"""Genome-browser/expression DB adapters (UCSC/Ensembl/NCBI-GEO), tested
against httpx's built-in `MockTransport` (same pattern
`test_bio_direct_adapters.py` uses) so no real network call/external mock
server is needed while still exercising the real HTTP request/response
handling logic."""
import httpx
import pytest

from src.infrastructure.mcp.expression_browser_db_adapters import (
    ExpressionBrowserAPIError,
    ExpressionBrowserDBAdapters,
    register_expression_browser_db_tools,
)
from src.infrastructure.mcp.server_registry import MCPServerRegistry


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- query_ucsc -------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_ucsc_track_mode_success_returns_items():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "downloadTime": "2024:01:01T00:00:00Z",
                "genome": "hg38",
                "track": "gold",
                "chrom": "chrM",
                "start": 0,
                "end": 100,
                "trackType": "bed",
                "itemsReturned": 1,
                "gold": [{"chrom": "chrM", "chromStart": 0, "chromEnd": 100, "type": "F"}],
            },
        )

    client = _client(handler)
    adapters = ExpressionBrowserDBAdapters(client)

    result = await adapters.query_ucsc({"genome": "hg38", "track": "gold", "chrom": "chrM"})

    assert result["genome"] == "hg38"
    assert result["track"] == "gold"
    assert result["items_returned"] == 1
    assert result["items"] == [{"chrom": "chrM", "chromStart": 0, "chromEnd": 100, "type": "F"}]
    # Built by hand with `;` separators (UCSC's documented/verified format),
    # not httpx's default `&`-joined params encoder.
    assert captured["url"] == (
        "https://api.genome.ucsc.edu/getData/track?genome=hg38;track=gold;chrom=chrM"
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_query_ucsc_track_mode_with_region_and_max_items_builds_semicolon_query():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"genome": "hg38", "track": "gold", "itemsReturned": 0, "gold": []},
        )

    client = _client(handler)
    adapters = ExpressionBrowserDBAdapters(client)

    await adapters.query_ucsc(
        {"genome": "hg38", "track": "gold", "chrom": "chr1", "start": 47000, "end": 48000, "max_items": 100}
    )

    assert captured["url"] == (
        "https://api.genome.ucsc.edu/getData/track?genome=hg38;track=gold;chrom=chr1;"
        "start=47000;end=48000;maxItemsOutput=100"
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_query_ucsc_list_tracks_mode_success_returns_track_map():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"genome": "hg38", "hg38": {"gold": {"shortLabel": "Assembly"}, "gap": {"shortLabel": "Gap"}}},
        )

    client = _client(handler)
    adapters = ExpressionBrowserDBAdapters(client)

    result = await adapters.query_ucsc({"genome": "hg38"})

    assert result == {
        "genome": "hg38",
        "track_count": 2,
        "tracks": {"gold": {"shortLabel": "Assembly"}, "gap": {"shortLabel": "Gap"}},
    }
    assert captured["url"] == "https://api.genome.ucsc.edu/list/tracks?genome=hg38"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_ucsc_missing_genome_raises_value_error():
    adapters = ExpressionBrowserDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'genome'"):
        await adapters.query_ucsc({})

    with pytest.raises(ValueError, match="non-empty 'genome'"):
        await adapters.query_ucsc(None)


@pytest.mark.asyncio
async def test_query_ucsc_structured_400_error_raises_expression_browser_api_error():
    # UCSC reports bad genome/track as a structured HTTP 400, not a 404 --
    # verified live against api.genome.ucsc.edu.
    client = _client(
        lambda r: httpx.Response(
            400,
            json={
                "error": "can not find genome='bogus' for endpoint '/list/tracks'",
                "statusCode": 400,
            },
        )
    )
    adapters = ExpressionBrowserDBAdapters(client)

    with pytest.raises(ExpressionBrowserAPIError, match="can not find genome"):
        await adapters.query_ucsc({"genome": "bogus"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_ucsc_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = ExpressionBrowserDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_ucsc({"genome": "hg38"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_ucsc_track_mode_malformed_body_raises_expression_browser_api_error():
    client = _client(lambda r: httpx.Response(200, json={"genome": "hg38", "track": "gold"}))
    adapters = ExpressionBrowserDBAdapters(client)

    with pytest.raises(ExpressionBrowserAPIError, match="expected item list"):
        await adapters.query_ucsc({"genome": "hg38", "track": "gold"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_ucsc_list_mode_malformed_body_raises_expression_browser_api_error():
    client = _client(lambda r: httpx.Response(200, json={"genome": "hg38"}))
    adapters = ExpressionBrowserDBAdapters(client)

    with pytest.raises(ExpressionBrowserAPIError, match="expected track map"):
        await adapters.query_ucsc({"genome": "hg38"})
    await client.aclose()


# --- query_ensembl -----------------------------------------------------------


@pytest.mark.asyncio
async def test_query_ensembl_success_returns_gene_data():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "id": "ENSG00000139618",
                "display_name": "BRCA2",
                "biotype": "protein_coding",
                "seq_region_name": "13",
                "start": 32315086,
                "end": 32400268,
            },
        )

    client = _client(handler)
    adapters = ExpressionBrowserDBAdapters(client)

    result = await adapters.query_ensembl({"symbol": "BRCA2"})

    assert result["id"] == "ENSG00000139618"
    assert result["display_name"] == "BRCA2"
    assert "/lookup/symbol/homo_sapiens/BRCA2" in captured["url"]
    await client.aclose()


@pytest.mark.asyncio
async def test_query_ensembl_uses_species_and_expand_args():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"id": "ENSMUSG00000041147", "display_name": "Brca2"})

    client = _client(handler)
    adapters = ExpressionBrowserDBAdapters(client)

    await adapters.query_ensembl({"symbol": "Brca2", "species": "mus_musculus", "expand": True})

    assert "/lookup/symbol/mus_musculus/Brca2" in captured["url"]
    assert "expand=1" in captured["url"]
    await client.aclose()


@pytest.mark.asyncio
async def test_query_ensembl_missing_symbol_raises_value_error():
    adapters = ExpressionBrowserDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'symbol'"):
        await adapters.query_ensembl({})

    with pytest.raises(ValueError, match="non-empty 'symbol'"):
        await adapters.query_ensembl(None)


@pytest.mark.asyncio
async def test_query_ensembl_not_found_400_raises_expression_browser_api_error():
    client = _client(
        lambda r: httpx.Response(400, json={"error": "No valid lookup found for symbol NOTAREAL"})
    )
    adapters = ExpressionBrowserDBAdapters(client)

    with pytest.raises(ExpressionBrowserAPIError, match="No valid lookup found"):
        await adapters.query_ensembl({"symbol": "NOTAREAL"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_ensembl_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = ExpressionBrowserDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_ensembl({"symbol": "BRCA2"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_ensembl_malformed_body_raises_expression_browser_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = ExpressionBrowserDBAdapters(client)

    with pytest.raises(ExpressionBrowserAPIError, match="expected gene data"):
        await adapters.query_ensembl({"symbol": "BRCA2"})
    await client.aclose()


# --- query_geo ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_geo_success_combines_esearch_and_esummary():
    captured_urls = []

    def handler(request):
        captured_urls.append(str(request.url))
        if "esearch.fcgi" in str(request.url):
            return httpx.Response(
                200,
                json={"esearchresult": {"count": "1", "idlist": ["200012345"]}},
            )
        if "esummary.fcgi" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "uids": ["200012345"],
                        "200012345": {"accession": "GSE12345", "title": "A study", "gdstype": "Expression profiling"},
                    }
                },
            )
        return httpx.Response(500)

    client = _client(handler)
    adapters = ExpressionBrowserDBAdapters(client)

    result = await adapters.query_geo({"search_term": "GSE12345[Accession]"})

    assert result["search_term"] == "GSE12345[Accession]"
    assert result["count"] == "1"
    assert result["records"] == [
        {"accession": "GSE12345", "title": "A study", "gdstype": "Expression profiling"}
    ]
    assert any("db=gds" in u and "esearch.fcgi" in u for u in captured_urls)
    assert any("id=200012345" in u and "esummary.fcgi" in u for u in captured_urls)
    await client.aclose()


@pytest.mark.asyncio
async def test_query_geo_no_results_returns_empty_records_without_esummary_call():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"esearchresult": {"count": "0", "idlist": []}})

    client = _client(handler)
    adapters = ExpressionBrowserDBAdapters(client)

    result = await adapters.query_geo({"search_term": "no such thing at all xyz"})

    assert result == {"search_term": "no such thing at all xyz", "count": "0", "records": []}
    assert len(calls) == 1  # esummary is never called when idlist is empty.
    await client.aclose()


@pytest.mark.asyncio
async def test_query_geo_missing_search_term_raises_value_error():
    adapters = ExpressionBrowserDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'search_term'"):
        await adapters.query_geo({})

    with pytest.raises(ValueError, match="non-empty 'search_term'"):
        await adapters.query_geo(None)


@pytest.mark.asyncio
async def test_query_geo_upstream_500_on_esearch_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = ExpressionBrowserDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_geo({"search_term": "breast cancer"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_geo_malformed_esearch_body_raises_expression_browser_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = ExpressionBrowserDBAdapters(client)

    with pytest.raises(ExpressionBrowserAPIError, match="esearch response"):
        await adapters.query_geo({"search_term": "breast cancer"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_geo_malformed_esummary_body_raises_expression_browser_api_error():
    def handler(request):
        if "esearch.fcgi" in str(request.url):
            return httpx.Response(200, json={"esearchresult": {"count": "1", "idlist": ["1"]}})
        return httpx.Response(200, json={"unexpected": "shape"})

    client = _client(handler)
    adapters = ExpressionBrowserDBAdapters(client)

    with pytest.raises(ExpressionBrowserAPIError, match="esummary response"):
        await adapters.query_geo({"search_term": "breast cancer"})
    await client.aclose()


# --- register_expression_browser_db_tools -------------------------------------


@pytest.mark.asyncio
async def test_register_expression_browser_db_tools_makes_all_three_tools_routable():
    def handler(request):
        url = str(request.url)
        if "api.genome.ucsc.edu" in url:
            return httpx.Response(200, json={"genome": "hg38", "hg38": {"gold": {}}})
        if "rest.ensembl.org" in url:
            return httpx.Response(200, json={"id": "ENSG00000139618", "display_name": "BRCA2"})
        if "esearch.fcgi" in url:
            return httpx.Response(200, json={"esearchresult": {"count": "0", "idlist": []}})
        return httpx.Response(500)

    client = _client(handler)
    registry = MCPServerRegistry()

    registered = register_expression_browser_db_tools(registry, client)

    assert set(registered) == {"query_ucsc", "query_ensembl", "query_geo"}
    assert set(registered).issubset(registry.registry.keys())

    ucsc_out = await registry.route("query_ucsc", {"genome": "hg38"})
    assert "gold" in ucsc_out

    ensembl_out = await registry.route("query_ensembl", {"symbol": "BRCA2"})
    assert "ENSG00000139618" in ensembl_out

    geo_out = await registry.route("query_geo", {"search_term": "nothing"})
    assert "records" in geo_out

    await client.aclose()


@pytest.mark.asyncio
async def test_register_expression_browser_db_tools_without_injected_client_uses_default_names():
    # No client injected -> ExpressionBrowserDBAdapters would build a real
    # httpx.AsyncClient per call. We only assert registration here (no real
    # network call is made in this test), matching how `bio_direct_adapters.py`'s
    # own registration-only test works.
    registry = MCPServerRegistry()

    registered = register_expression_browser_db_tools(registry)

    assert set(registered) == {"query_ucsc", "query_ensembl", "query_geo"}
