"""Taxonomy/ecology/paleontology DB adapters: IUCN Red List v4 / Paleobiology
Database (PBDB) / WoRMS / Mouse Phenome Database (MPD) REST API adapters,
tested against httpx's built-in `MockTransport` (same pattern
`test_bio_direct_adapters.py` uses) so no real network call/external mock
server is needed while still exercising the real HTTP request/response
handling logic."""
import httpx
import pytest

from src.infrastructure.mcp.server_registry import MCPServerRegistry
from src.infrastructure.mcp.taxonomy_db_adapters import (
    TaxonomyAPIError,
    TaxonomyDBAdapters,
    register_taxonomy_db_tools,
)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- query_iucn -------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_iucn_success_returns_taxon_and_assessments():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "genus_name": "Panthera",
                "species_name": "leo",
                "taxon": {"sis_id": 15951, "scientific_name": "Panthera leo"},
                "assessments": [
                    {"year_published": "2016", "latest": True, "red_list_category_code": "VU"}
                ],
            },
        )

    client = _client(handler)
    adapters = TaxonomyDBAdapters(client, iucn_api_token="fake-token")

    result = await adapters.query_iucn({"genus_name": "Panthera", "species_name": "leo"})

    assert result["genus_name"] == "Panthera"
    assert result["species_name"] == "leo"
    assert result["taxon"]["scientific_name"] == "Panthera leo"
    assert result["assessments"][0]["red_list_category_code"] == "VU"
    assert "genus_name=Panthera" in captured["url"]
    assert "species_name=leo" in captured["url"]
    assert captured["headers"]["authorization"] == "Bearer fake-token"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_iucn_missing_args_raise_value_error():
    adapters = TaxonomyDBAdapters(_client(lambda r: httpx.Response(200, json={})), iucn_api_token="t")

    with pytest.raises(ValueError, match="non-empty 'genus_name'"):
        await adapters.query_iucn({"species_name": "leo"})

    with pytest.raises(ValueError, match="non-empty 'species_name'"):
        await adapters.query_iucn({"genus_name": "Panthera"})

    with pytest.raises(ValueError, match="non-empty 'genus_name'"):
        await adapters.query_iucn(None)


@pytest.mark.asyncio
async def test_query_iucn_missing_token_raises_value_error():
    adapters = TaxonomyDBAdapters(
        _client(lambda r: httpx.Response(200, json={})), iucn_api_token=None
    )

    with pytest.raises(ValueError, match="IUCN_API_TOKEN"):
        await adapters.query_iucn({"genus_name": "Panthera", "species_name": "leo"})


@pytest.mark.asyncio
async def test_query_iucn_404_raises_taxonomy_api_error():
    client = _client(lambda r: httpx.Response(404, json={"error": "not found"}))
    adapters = TaxonomyDBAdapters(client, iucn_api_token="t")

    with pytest.raises(TaxonomyAPIError, match="no taxon matching"):
        await adapters.query_iucn({"genus_name": "Nosuch", "species_name": "genus"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_iucn_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = TaxonomyDBAdapters(client, iucn_api_token="t")

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_iucn({"genus_name": "Panthera", "species_name": "leo"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_iucn_malformed_body_raises_taxonomy_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = TaxonomyDBAdapters(client, iucn_api_token="t")

    with pytest.raises(TaxonomyAPIError, match="expected assessment data"):
        await adapters.query_iucn({"genus_name": "Panthera", "species_name": "leo"})
    await client.aclose()


# --- query_paleobiology ------------------------------------------------------


@pytest.mark.asyncio
async def test_query_paleobiology_success_returns_first_record():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "records": [
                    {
                        "taxon_name": "Tyrannosaurus",
                        "taxon_rank": "genus",
                        "n_occs": 87,
                    }
                ],
                "elapsed_time": 0.002,
            },
        )

    client = _client(handler)
    adapters = TaxonomyDBAdapters(client)

    result = await adapters.query_paleobiology({"taxon_name": "Tyrannosaurus"})

    assert result == {"taxon_name": "Tyrannosaurus", "taxon_rank": "genus", "n_occs": 87}
    assert "name=Tyrannosaurus" in captured["url"]
    assert "vocab=pbdb" in captured["url"]
    await client.aclose()


@pytest.mark.asyncio
async def test_query_paleobiology_missing_taxon_name_raises_value_error():
    adapters = TaxonomyDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'taxon_name'"):
        await adapters.query_paleobiology({})

    with pytest.raises(ValueError, match="non-empty 'taxon_name'"):
        await adapters.query_paleobiology(None)


@pytest.mark.asyncio
async def test_query_paleobiology_404_raises_taxonomy_api_error():
    client = _client(lambda r: httpx.Response(404, text="not found"))
    adapters = TaxonomyDBAdapters(client)

    with pytest.raises(TaxonomyAPIError, match="no taxon matching"):
        await adapters.query_paleobiology({"taxon_name": "Notarealtaxon"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_paleobiology_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = TaxonomyDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_paleobiology({"taxon_name": "Tyrannosaurus"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_paleobiology_malformed_body_raises_taxonomy_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = TaxonomyDBAdapters(client)

    with pytest.raises(TaxonomyAPIError, match="expected taxon record"):
        await adapters.query_paleobiology({"taxon_name": "Tyrannosaurus"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_paleobiology_empty_records_raises_taxonomy_api_error():
    client = _client(lambda r: httpx.Response(200, json={"records": []}))
    adapters = TaxonomyDBAdapters(client)

    with pytest.raises(TaxonomyAPIError, match="expected taxon record"):
        await adapters.query_paleobiology({"taxon_name": "Tyrannosaurus"})
    await client.aclose()


# --- query_worms --------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_worms_success_returns_list():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json=[
                {
                    "AphiaID": 127160,
                    "scientificname": "Solea solea",
                    "status": "accepted",
                    "rank": "Species",
                }
            ],
        )

    client = _client(handler)
    adapters = TaxonomyDBAdapters(client)

    result = await adapters.query_worms({"scientific_name": "Solea solea"})

    assert result == [
        {"AphiaID": 127160, "scientificname": "Solea solea", "status": "accepted", "rank": "Species"}
    ]
    assert "AphiaRecordsByName/Solea%20solea" in captured["url"]
    await client.aclose()


@pytest.mark.asyncio
async def test_query_worms_missing_scientific_name_raises_value_error():
    adapters = TaxonomyDBAdapters(_client(lambda r: httpx.Response(200, json=[])))

    with pytest.raises(ValueError, match="non-empty 'scientific_name'"):
        await adapters.query_worms({})

    with pytest.raises(ValueError, match="non-empty 'scientific_name'"):
        await adapters.query_worms(None)


@pytest.mark.asyncio
async def test_query_worms_204_raises_taxonomy_api_error():
    client = _client(lambda r: httpx.Response(204))
    adapters = TaxonomyDBAdapters(client)

    with pytest.raises(TaxonomyAPIError, match="no record matching"):
        await adapters.query_worms({"scientific_name": "Notarealfish"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_worms_empty_list_raises_taxonomy_api_error():
    client = _client(lambda r: httpx.Response(200, json=[]))
    adapters = TaxonomyDBAdapters(client)

    with pytest.raises(TaxonomyAPIError, match="no record matching"):
        await adapters.query_worms({"scientific_name": "Notarealfish"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_worms_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = TaxonomyDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_worms({"scientific_name": "Solea solea"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_worms_non_list_response_raises_taxonomy_api_error():
    client = _client(lambda r: httpx.Response(200, json={"error": "malformed"}))
    adapters = TaxonomyDBAdapters(client)

    with pytest.raises(TaxonomyAPIError, match="unexpected response shape"):
        await adapters.query_worms({"scientific_name": "Solea solea"})
    await client.aclose()


# --- query_mpd -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_mpd_success_returns_strainmeans():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "count": 2,
                "strainmeans": [
                    {"strain": "C57BL/6J", "measnum": 2908, "mean": 1.23, "sex": "f"},
                    {"strain": "A/J", "measnum": 2908, "mean": 4.56, "sex": "m"},
                ],
            },
        )

    client = _client(handler)
    adapters = TaxonomyDBAdapters(client)

    result = await adapters.query_mpd({"measnum": 2908})

    assert result["measnum"] == "2908"
    assert result["count"] == 2
    assert len(result["strainmeans"]) == 2
    assert "/pheno/strainmeans/2908" in captured["url"]
    await client.aclose()


@pytest.mark.asyncio
async def test_query_mpd_accepts_list_of_measnums():
    client = _client(
        lambda r: httpx.Response(200, json={"count": 0, "strainmeans": []})
    )
    adapters = TaxonomyDBAdapters(client)

    result = await adapters.query_mpd({"measnum": [2908, 2909]})

    assert result["measnum"] == "2908,2909"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_mpd_missing_measnum_raises_value_error():
    adapters = TaxonomyDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'measnum'"):
        await adapters.query_mpd({})

    with pytest.raises(ValueError, match="non-empty 'measnum'"):
        await adapters.query_mpd(None)


@pytest.mark.asyncio
async def test_query_mpd_404_raises_taxonomy_api_error():
    client = _client(lambda r: httpx.Response(404, text="not found"))
    adapters = TaxonomyDBAdapters(client)

    with pytest.raises(TaxonomyAPIError, match="no strain-means data"):
        await adapters.query_mpd({"measnum": 99999999})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_mpd_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = TaxonomyDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_mpd({"measnum": 2908})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_mpd_malformed_body_raises_taxonomy_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = TaxonomyDBAdapters(client)

    with pytest.raises(TaxonomyAPIError, match="expected 'strainmeans' data"):
        await adapters.query_mpd({"measnum": 2908})
    await client.aclose()


# --- register_taxonomy_db_tools -------------------------------------------


@pytest.mark.asyncio
async def test_register_taxonomy_db_tools_makes_all_four_tools_routable():
    def handler(request):
        url = str(request.url)
        if "iucnredlist.org" in url:
            return httpx.Response(200, json={"assessments": [{"red_list_category_code": "LC"}]})
        if "paleobiodb.org" in url:
            return httpx.Response(200, json={"records": [{"taxon_name": "Tyrannosaurus"}]})
        if "marinespecies.org" in url:
            return httpx.Response(200, json=[{"scientificname": "Solea solea"}])
        if "phenome.jax.org" in url:
            return httpx.Response(200, json={"count": 1, "strainmeans": [{"strain": "C57BL/6J"}]})
        return httpx.Response(500)

    client = _client(handler)
    registry = MCPServerRegistry()

    registered = register_taxonomy_db_tools(registry, client, iucn_api_token="fake-token")

    assert set(registered) == {"query_iucn", "query_paleobiology", "query_worms", "query_mpd"}
    assert set(registered).issubset(registry.registry.keys())

    iucn_out = await registry.route("query_iucn", {"genus_name": "Panthera", "species_name": "leo"})
    assert "LC" in iucn_out

    pbdb_out = await registry.route("query_paleobiology", {"taxon_name": "Tyrannosaurus"})
    assert "Tyrannosaurus" in pbdb_out

    worms_out = await registry.route("query_worms", {"scientific_name": "Solea solea"})
    assert "Solea solea" in worms_out

    mpd_out = await registry.route("query_mpd", {"measnum": 2908})
    assert "C57BL/6J" in mpd_out

    await client.aclose()


@pytest.mark.asyncio
async def test_register_taxonomy_db_tools_without_injected_client_uses_default_names():
    # No client injected -> TaxonomyDBAdapters would build a real
    # httpx.AsyncClient per call. We only assert registration here (no real
    # network call is made in this test), matching how `bio_direct_adapters.py`'s
    # own registration-only test works.
    registry = MCPServerRegistry()

    registered = register_taxonomy_db_tools(registry)

    assert set(registered) == {"query_iucn", "query_paleobiology", "query_worms", "query_mpd"}
