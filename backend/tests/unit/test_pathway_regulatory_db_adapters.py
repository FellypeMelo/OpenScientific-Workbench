"""Pathway/interaction/regulatory-database adapter tests (KEGG/STRING/Reactome/
RegulomeDB/JASPAR/ENCODE-SCREEN/ReMap), tested against httpx's built-in
`MockTransport` (same pattern `test_bio_direct_adapters.py` uses) so no real
network call/external mock server is needed while still exercising the real
HTTP request/response handling logic."""
import httpx
import pytest

from src.infrastructure.mcp.pathway_regulatory_db_adapters import (
    PathwayRegulatoryAPIError,
    PathwayRegulatoryDBAdapters,
    register_pathway_regulatory_db_tools,
)
from src.infrastructure.mcp.server_registry import MCPServerRegistry


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- query_kegg -------------------------------------------------------


@pytest.mark.asyncio
async def test_query_kegg_success_returns_operation_target_and_text_result():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, text="ENTRY       hsa:7157          CDS\nNAME        TP53\n")

    client = _client(handler)
    adapters = PathwayRegulatoryDBAdapters(client)

    result = await adapters.query_kegg({"operation": "get", "target": "hsa:7157"})

    assert result["operation"] == "get"
    assert result["target"] == "hsa:7157"
    assert result["option"] is None
    assert "TP53" in result["result"]
    assert captured["url"] == "https://rest.kegg.jp/get/hsa:7157"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_kegg_with_option_appends_third_path_segment():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, text=">hsa:7157\nMEEPQ...\n")

    client = _client(handler)
    adapters = PathwayRegulatoryDBAdapters(client)

    result = await adapters.query_kegg({"operation": "get", "target": "hsa:7157", "option": "aaseq"})

    assert result["option"] == "aaseq"
    assert captured["url"] == "https://rest.kegg.jp/get/hsa:7157/aaseq"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_kegg_missing_operation_raises_value_error():
    adapters = PathwayRegulatoryDBAdapters(_client(lambda r: httpx.Response(200, text="x")))

    with pytest.raises(ValueError, match="'operation'"):
        await adapters.query_kegg({"target": "hsa:7157"})

    with pytest.raises(ValueError, match="'operation'"):
        await adapters.query_kegg({"operation": "bogus", "target": "hsa:7157"})


@pytest.mark.asyncio
async def test_query_kegg_missing_target_raises_value_error():
    adapters = PathwayRegulatoryDBAdapters(_client(lambda r: httpx.Response(200, text="x")))

    with pytest.raises(ValueError, match="non-empty 'target'"):
        await adapters.query_kegg({"operation": "get"})


@pytest.mark.asyncio
async def test_query_kegg_404_raises_pathway_regulatory_api_error():
    client = _client(lambda r: httpx.Response(404, text="not found"))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(PathwayRegulatoryAPIError, match="no results"):
        await adapters.query_kegg({"operation": "get", "target": "hsa:99999999"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_kegg_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_kegg({"operation": "get", "target": "hsa:7157"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_kegg_empty_body_raises_pathway_regulatory_api_error():
    client = _client(lambda r: httpx.Response(200, text="   "))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(PathwayRegulatoryAPIError, match="empty response"):
        await adapters.query_kegg({"operation": "get", "target": "hsa:7157"})
    await client.aclose()


# --- query_stringdb -------------------------------------------------------


@pytest.mark.asyncio
async def test_query_stringdb_get_string_ids_success_returns_list():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200, json=[{"stringId": "9606.ENSP00000269305", "preferredName": "TP53"}]
        )

    client = _client(handler)
    adapters = PathwayRegulatoryDBAdapters(client)

    result = await adapters.query_stringdb({"method": "get_string_ids", "identifiers": "TP53"})

    assert result == [{"stringId": "9606.ENSP00000269305", "preferredName": "TP53"}]
    assert "get_string_ids" in captured["url"]
    assert captured["params"]["identifiers"] == "TP53"
    assert captured["params"]["species"] == "9606"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_stringdb_version_does_not_require_identifiers():
    client = _client(lambda r: httpx.Response(200, json={"string_version": "12.0"}))
    adapters = PathwayRegulatoryDBAdapters(client)

    result = await adapters.query_stringdb({"method": "version"})

    assert result == {"string_version": "12.0"}
    await client.aclose()


@pytest.mark.asyncio
async def test_query_stringdb_missing_method_raises_value_error():
    adapters = PathwayRegulatoryDBAdapters(_client(lambda r: httpx.Response(200, json=[])))

    with pytest.raises(ValueError, match="'method'"):
        await adapters.query_stringdb({})

    with pytest.raises(ValueError, match="'method'"):
        await adapters.query_stringdb({"method": "network"})


@pytest.mark.asyncio
async def test_query_stringdb_missing_identifiers_raises_value_error():
    adapters = PathwayRegulatoryDBAdapters(_client(lambda r: httpx.Response(200, json=[])))

    with pytest.raises(ValueError, match="non-empty 'identifiers'"):
        await adapters.query_stringdb({"method": "enrichment"})


@pytest.mark.asyncio
async def test_query_stringdb_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_stringdb({"method": "get_string_ids", "identifiers": "TP53"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_stringdb_malformed_body_raises_pathway_regulatory_api_error():
    client = _client(lambda r: httpx.Response(200, json="not a list or object"))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(PathwayRegulatoryAPIError, match="unexpected response shape"):
        await adapters.query_stringdb({"method": "get_string_ids", "identifiers": "TP53"})
    await client.aclose()


# --- query_reactome ---------------------------------------------------


@pytest.mark.asyncio
async def test_query_reactome_by_id_success():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200, json={"dbId": 1640170, "displayName": "Cell Cycle", "stId": "R-HSA-1640170"}
        )

    client = _client(handler)
    adapters = PathwayRegulatoryDBAdapters(client)

    result = await adapters.query_reactome({"id": "R-HSA-1640170"})

    assert result["stId"] == "R-HSA-1640170"
    assert captured["url"] == "https://reactome.org/ContentService/data/query/R-HSA-1640170"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_reactome_by_search_query_success():
    captured = {}

    def handler(request):
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"results": [{"exactType": "Pathway"}]})

    client = _client(handler)
    adapters = PathwayRegulatoryDBAdapters(client)

    result = await adapters.query_reactome({"query": "DNA repair"})

    assert result == {"results": [{"exactType": "Pathway"}]}
    assert captured["params"]["query"] == "DNA repair"
    assert captured["params"]["species"] == "Homo sapiens"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_reactome_missing_id_and_query_raises_value_error():
    adapters = PathwayRegulatoryDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="'id'.*'query'"):
        await adapters.query_reactome({})

    with pytest.raises(ValueError, match="'id'.*'query'"):
        await adapters.query_reactome(None)


@pytest.mark.asyncio
async def test_query_reactome_404_raises_pathway_regulatory_api_error():
    client = _client(lambda r: httpx.Response(404, text="not found"))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(PathwayRegulatoryAPIError, match="was not found"):
        await adapters.query_reactome({"id": "R-HSA-0000000"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_reactome_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_reactome({"id": "R-HSA-1640170"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_reactome_malformed_body_raises_pathway_regulatory_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(PathwayRegulatoryAPIError, match="expected entity data"):
        await adapters.query_reactome({"id": "R-HSA-1640170"})
    await client.aclose()


# --- query_regulomedb -----------------------------------------------------


@pytest.mark.asyncio
async def test_query_regulomedb_success():
    captured = {}

    def handler(request):
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"@context": "/terms/", "@graph": [{"chrom": "chr11"}]})

    client = _client(handler)
    adapters = PathwayRegulatoryDBAdapters(client)

    result = await adapters.query_regulomedb({"region": "rs35675666"})

    assert result["@graph"] == [{"chrom": "chr11"}]
    assert captured["params"]["regions"] == "rs35675666"
    assert captured["params"]["genome"] == "GRCh38"
    assert captured["params"]["format"] == "json"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_regulomedb_missing_region_raises_value_error():
    adapters = PathwayRegulatoryDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'region'"):
        await adapters.query_regulomedb({})

    with pytest.raises(ValueError, match="non-empty 'region'"):
        await adapters.query_regulomedb(None)


@pytest.mark.asyncio
async def test_query_regulomedb_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_regulomedb({"region": "rs35675666"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_regulomedb_malformed_body_raises_pathway_regulatory_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(PathwayRegulatoryAPIError, match="expected"):
        await adapters.query_regulomedb({"region": "rs35675666"})
    await client.aclose()


# --- query_jaspar -----------------------------------------------------


@pytest.mark.asyncio
async def test_query_jaspar_by_matrix_id_success():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"matrix_id": "MA0002.2", "name": "RUNX1"})

    client = _client(handler)
    adapters = PathwayRegulatoryDBAdapters(client)

    result = await adapters.query_jaspar({"matrix_id": "MA0002.2"})

    assert result == {"matrix_id": "MA0002.2", "name": "RUNX1"}
    assert captured["url"] == "https://jaspar.elixir.no/api/v1/matrix/MA0002.2/"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_jaspar_search_success():
    captured = {}

    def handler(request):
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"count": 1, "results": [{"matrix_id": "MA0002.2"}]})

    client = _client(handler)
    adapters = PathwayRegulatoryDBAdapters(client)

    result = await adapters.query_jaspar({"name": "RUNX1", "tax_id": 9606})

    assert result["results"] == [{"matrix_id": "MA0002.2"}]
    assert captured["params"]["name"] == "RUNX1"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_jaspar_no_args_raises_value_error():
    adapters = PathwayRegulatoryDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="'matrix_id'"):
        await adapters.query_jaspar({})

    with pytest.raises(ValueError, match="'matrix_id'"):
        await adapters.query_jaspar(None)


@pytest.mark.asyncio
async def test_query_jaspar_404_raises_pathway_regulatory_api_error():
    client = _client(lambda r: httpx.Response(404, text="not found"))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(PathwayRegulatoryAPIError, match="was not found"):
        await adapters.query_jaspar({"matrix_id": "MA9999.9"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_jaspar_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_jaspar({"matrix_id": "MA0002.2"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_jaspar_malformed_body_raises_pathway_regulatory_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(PathwayRegulatoryAPIError, match="expected profile data"):
        await adapters.query_jaspar({"matrix_id": "MA0002.2"})
    await client.aclose()


# --- region_to_ccre_screen ------------------------------------------------


@pytest.mark.asyncio
async def test_region_to_ccre_screen_success():
    captured = {}

    def handler(request):
        captured["method"] = request.method
        captured["body"] = request.read()
        return httpx.Response(
            200,
            json={
                "cres": [
                    {
                        "chrom": "chr12",
                        "start": 100,
                        "len": 200,
                        "pct": "PLS",
                        "ctcf_zscore": 0.1,
                        "dnase_zscore": 1.234,
                        "enhancer_zscore": 0.2,
                        "promoter_zscore": 0.3,
                        "info": {
                            "accession": "EH38E1516980",
                            "isproximal": True,
                            "concordant": True,
                            "ctcfmax": 0.1,
                            "k4me3max": 0.2,
                            "k27acmax": 0.3,
                        },
                    }
                ]
            },
        )

    client = _client(handler)
    adapters = PathwayRegulatoryDBAdapters(client)

    result = await adapters.region_to_ccre_screen(
        {"chrom": "chr12", "start": 100, "end": 300, "assembly": "GRCh38"}
    )

    assert result["cres"][0]["info"]["accession"] == "EH38E1516980"
    assert captured["method"] == "POST"
    assert b"chr12" in captured["body"]
    await client.aclose()


@pytest.mark.asyncio
async def test_region_to_ccre_screen_missing_coords_raises_value_error():
    adapters = PathwayRegulatoryDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'chrom'"):
        await adapters.region_to_ccre_screen({"start": 1, "end": 2})

    with pytest.raises(ValueError, match="'start' and 'end'"):
        await adapters.region_to_ccre_screen({"chrom": "chr12"})

    with pytest.raises(ValueError, match="non-empty 'chrom'"):
        await adapters.region_to_ccre_screen(None)


@pytest.mark.asyncio
async def test_region_to_ccre_screen_non_integer_coords_raises_value_error():
    adapters = PathwayRegulatoryDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="must be integers"):
        await adapters.region_to_ccre_screen({"chrom": "chr12", "start": "abc", "end": 300})


@pytest.mark.asyncio
async def test_region_to_ccre_screen_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.region_to_ccre_screen({"chrom": "chr12", "start": 100, "end": 300})
    await client.aclose()


@pytest.mark.asyncio
async def test_region_to_ccre_screen_malformed_body_raises_pathway_regulatory_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(PathwayRegulatoryAPIError, match="expected 'cres' data"):
        await adapters.region_to_ccre_screen({"chrom": "chr12", "start": 100, "end": 300})
    await client.aclose()


@pytest.mark.asyncio
async def test_region_to_ccre_screen_api_error_field_raises_pathway_regulatory_api_error():
    client = _client(lambda r: httpx.Response(200, json={"errors": ["bad assembly"]}))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(PathwayRegulatoryAPIError, match="bad assembly"):
        await adapters.region_to_ccre_screen({"chrom": "chr12", "start": 100, "end": 300})
    await client.aclose()


# --- get_genes_near_ccre ---------------------------------------------


@pytest.mark.asyncio
async def test_get_genes_near_ccre_success_sorts_and_limits_by_distance():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "EH38E1516980": {
                    "nearby_genes": [
                        {"name": "GENE_FAR", "distance": 5000, "chrom": "chr12"},
                        {"name": "GENE_NEAR", "distance": 100, "chrom": "chr12"},
                        {"name": "GENE_MID", "distance": 1000, "chrom": "chr12"},
                    ]
                }
            },
        )

    client = _client(handler)
    adapters = PathwayRegulatoryDBAdapters(client)

    result = await adapters.get_genes_near_ccre(
        {"accession": "EH38E1516980", "chromosome": "chr12", "k": 2}
    )

    assert [g["name"] for g in result["genes"]] == ["GENE_NEAR", "GENE_MID"]
    await client.aclose()


@pytest.mark.asyncio
async def test_get_genes_near_ccre_missing_args_raises_value_error():
    adapters = PathwayRegulatoryDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'accession'"):
        await adapters.get_genes_near_ccre({"chromosome": "chr12"})

    with pytest.raises(ValueError, match="non-empty 'chromosome'"):
        await adapters.get_genes_near_ccre({"accession": "EH38E1516980"})

    with pytest.raises(ValueError, match="non-empty 'accession'"):
        await adapters.get_genes_near_ccre(None)


@pytest.mark.asyncio
async def test_get_genes_near_ccre_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.get_genes_near_ccre({"accession": "EH38E1516980", "chromosome": "chr12"})
    await client.aclose()


@pytest.mark.asyncio
async def test_get_genes_near_ccre_missing_nearby_genes_raises_pathway_regulatory_api_error():
    client = _client(lambda r: httpx.Response(200, json={"OTHER_ACCESSION": {}}))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(PathwayRegulatoryAPIError, match="nearby_genes"):
        await adapters.get_genes_near_ccre({"accession": "EH38E1516980", "chromosome": "chr12"})
    await client.aclose()


# --- query_remap -------------------------------------------------------


@pytest.mark.asyncio
async def test_query_remap_success():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "region": "chr1:100000-150000",
                "peaks": [{"peakValues": {"chrom": "chr1", "name": {"TF": "CTCF"}}}],
            },
        )

    client = _client(handler)
    adapters = PathwayRegulatoryDBAdapters(client)

    result = await adapters.query_remap(
        {"chrom": "chr1", "start": 100000, "end": 150000, "target": "CTCF"}
    )

    assert result["peaks"][0]["peakValues"]["name"]["TF"] == "CTCF"
    assert captured["url"] == (
        "https://remap-rest.univ-amu.fr/api/V1/get_peaks/2022/hg38/all/"
        "chr1:100000-150000/target/CTCF"
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_query_remap_missing_coords_raises_value_error():
    adapters = PathwayRegulatoryDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'chrom'"):
        await adapters.query_remap({"start": 1, "end": 2})

    with pytest.raises(ValueError, match="'start' and 'end'"):
        await adapters.query_remap({"chrom": "chr1"})

    with pytest.raises(ValueError, match="non-empty 'chrom'"):
        await adapters.query_remap(None)


@pytest.mark.asyncio
async def test_query_remap_invalid_datatype_raises_value_error():
    adapters = PathwayRegulatoryDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="'datatype'"):
        await adapters.query_remap({"chrom": "chr1", "start": 1, "end": 2, "datatype": "bogus"})


@pytest.mark.asyncio
async def test_query_remap_404_raises_pathway_regulatory_api_error():
    client = _client(lambda r: httpx.Response(404, text="not found"))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(PathwayRegulatoryAPIError, match="no results"):
        await adapters.query_remap({"chrom": "chr1", "start": 1, "end": 2})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_remap_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_remap({"chrom": "chr1", "start": 1, "end": 2})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_remap_malformed_body_raises_pathway_regulatory_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = PathwayRegulatoryDBAdapters(client)

    with pytest.raises(PathwayRegulatoryAPIError, match="expected"):
        await adapters.query_remap({"chrom": "chr1", "start": 1, "end": 2})
    await client.aclose()


# --- register_pathway_regulatory_db_tools ------------------------------


@pytest.mark.asyncio
async def test_register_pathway_regulatory_db_tools_makes_all_tools_routable():
    def handler(request):
        url = str(request.url)
        if "rest.kegg.jp" in url:
            return httpx.Response(200, text="ENTRY dummy\n")
        if "string-db.org" in url:
            return httpx.Response(200, json=[{"stringId": "dummy"}])
        if "reactome.org" in url:
            return httpx.Response(200, json={"dbId": 1, "stId": "R-HSA-1"})
        if "regulomedb.org" in url:
            return httpx.Response(200, json={"@graph": []})
        if "jaspar.elixir.no" in url:
            return httpx.Response(200, json={"matrix_id": "MA0002.2"})
        if "screen-beta-api.wenglab.org/dataws/cre_table" in url:
            return httpx.Response(200, json={"cres": []})
        if "screen-beta-api.wenglab.org/dataws/re_detail/nearbyGenomic" in url:
            return httpx.Response(200, json={"EH38E1516980": {"nearby_genes": []}})
        if "remap-rest.univ-amu.fr" in url:
            return httpx.Response(200, json={"peaks": []})
        return httpx.Response(500)

    client = _client(handler)
    registry = MCPServerRegistry()

    registered = register_pathway_regulatory_db_tools(registry, client)

    assert set(registered) == {
        "query_kegg",
        "query_stringdb",
        "query_reactome",
        "query_regulomedb",
        "query_jaspar",
        "region_to_ccre_screen",
        "get_genes_near_ccre",
        "query_remap",
    }
    assert set(registered).issubset(registry.registry.keys())

    kegg_out = await registry.route("query_kegg", {"operation": "get", "target": "hsa:7157"})
    assert "ENTRY dummy" in kegg_out

    string_out = await registry.route(
        "query_stringdb", {"method": "get_string_ids", "identifiers": "TP53"}
    )
    assert "dummy" in string_out

    reactome_out = await registry.route("query_reactome", {"id": "R-HSA-1"})
    assert "R-HSA-1" in reactome_out

    regulome_out = await registry.route("query_regulomedb", {"region": "rs35675666"})
    assert "@graph" in regulome_out

    jaspar_out = await registry.route("query_jaspar", {"matrix_id": "MA0002.2"})
    assert "MA0002.2" in jaspar_out

    ccre_out = await registry.route(
        "region_to_ccre_screen", {"chrom": "chr12", "start": 1, "end": 2}
    )
    assert "cres" in ccre_out

    genes_out = await registry.route(
        "get_genes_near_ccre", {"accession": "EH38E1516980", "chromosome": "chr12"}
    )
    assert "genes" in genes_out

    remap_out = await registry.route("query_remap", {"chrom": "chr1", "start": 1, "end": 2})
    assert "peaks" in remap_out

    await client.aclose()


@pytest.mark.asyncio
async def test_register_pathway_regulatory_db_tools_without_injected_client_uses_default_names():
    # No client injected -> PathwayRegulatoryDBAdapters would build a real
    # httpx.AsyncClient per call. We only assert registration here (no real
    # network call is made in this test), matching how `bio_direct_adapters.py`'s
    # own registration-only test works.
    registry = MCPServerRegistry()

    registered = register_pathway_regulatory_db_tools(registry)

    assert set(registered) == {
        "query_kegg",
        "query_stringdb",
        "query_reactome",
        "query_regulomedb",
        "query_jaspar",
        "region_to_ccre_screen",
        "get_genes_near_ccre",
        "query_remap",
    }
