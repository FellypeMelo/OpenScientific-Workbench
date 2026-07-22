"""Fase 2 DB-adapter catalog, "structure" group: direct UniProt search /
AlphaFold / InterPro / RCSB PDB search / RCSB PDB batch identifiers / EMDB
REST API adapters, tested against httpx's built-in `MockTransport` (same
pattern `test_bio_direct_adapters.py` uses) so no real network call/external
mock server is needed while still exercising the real HTTP request/response
handling logic."""
import httpx
import pytest

from src.infrastructure.mcp.server_registry import MCPServerRegistry
from src.infrastructure.mcp.structure_db_adapters import (
    StructureAPIError,
    StructureDBAdapters,
    register_structure_db_tools,
)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- query_uniprot ----------------------------------------------------


@pytest.mark.asyncio
async def test_query_uniprot_success_returns_results_list():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"results": [{"primaryAccession": "P01308", "uniProtkbId": "INS_HUMAN"}]},
        )

    client = _client(handler)
    adapters = StructureDBAdapters(client)

    result = await adapters.query_uniprot({"query": "insulin"})

    assert result["query"] == "insulin"
    assert result["count"] == 1
    assert result["results"][0]["primaryAccession"] == "P01308"
    assert "rest.uniprot.org/uniprotkb/search" in captured["url"]
    assert "query=insulin" in captured["url"]
    await client.aclose()


@pytest.mark.asyncio
async def test_query_uniprot_missing_query_raises_value_error():
    adapters = StructureDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'query'"):
        await adapters.query_uniprot({})

    with pytest.raises(ValueError, match="non-empty 'query'"):
        await adapters.query_uniprot(None)


@pytest.mark.asyncio
async def test_query_uniprot_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = StructureDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_uniprot({"query": "insulin"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_uniprot_malformed_body_raises_structure_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = StructureDBAdapters(client)

    with pytest.raises(StructureAPIError, match="expected 'results' list"):
        await adapters.query_uniprot({"query": "insulin"})
    await client.aclose()


# --- query_alphafold ----------------------------------------------------


@pytest.mark.asyncio
async def test_query_alphafold_success_returns_predictions_list():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json=[{"uniprotAccession": "P69905", "cifUrl": "https://alphafold.ebi.ac.uk/files/x.cif"}],
        )

    client = _client(handler)
    adapters = StructureDBAdapters(client)

    result = await adapters.query_alphafold({"qualifier": "P69905"})

    assert result["qualifier"] == "P69905"
    assert result["count"] == 1
    assert result["predictions"][0]["uniprotAccession"] == "P69905"
    assert captured["url"] == "https://alphafold.ebi.ac.uk/api/prediction/P69905"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_alphafold_missing_qualifier_raises_value_error():
    adapters = StructureDBAdapters(_client(lambda r: httpx.Response(200, json=[])))

    with pytest.raises(ValueError, match="non-empty 'qualifier'"):
        await adapters.query_alphafold({})

    with pytest.raises(ValueError, match="non-empty 'qualifier'"):
        await adapters.query_alphafold(None)


@pytest.mark.asyncio
async def test_query_alphafold_404_raises_structure_api_error():
    client = _client(lambda r: httpx.Response(404, json={}))
    adapters = StructureDBAdapters(client)

    with pytest.raises(StructureAPIError, match="No AlphaFold DB prediction was found"):
        await adapters.query_alphafold({"qualifier": "NOTREAL"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_alphafold_400_raises_structure_api_error():
    client = _client(lambda r: httpx.Response(400, json={"error": "Invalid identifier format."}))
    adapters = StructureDBAdapters(client)

    with pytest.raises(StructureAPIError, match="invalid identifier"):
        await adapters.query_alphafold({"qualifier": "!!!"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_alphafold_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = StructureDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_alphafold({"qualifier": "P69905"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_alphafold_malformed_body_raises_structure_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = StructureDBAdapters(client)

    with pytest.raises(StructureAPIError, match="expected a list"):
        await adapters.query_alphafold({"qualifier": "P69905"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_alphafold_empty_list_raises_structure_api_error():
    client = _client(lambda r: httpx.Response(200, json=[]))
    adapters = StructureDBAdapters(client)

    with pytest.raises(StructureAPIError, match="no predictions"):
        await adapters.query_alphafold({"qualifier": "P69905"})
    await client.aclose()


# --- query_interpro ----------------------------------------------------


@pytest.mark.asyncio
async def test_query_interpro_success_returns_results_list():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "count": 1,
                "results": [{"metadata": {"accession": "IPR000971", "name": "Globin"}}],
            },
        )

    client = _client(handler)
    adapters = StructureDBAdapters(client)

    result = await adapters.query_interpro({"accession": "P69905"})

    assert result["accession"] == "P69905"
    assert result["source_database"] == "interpro"
    assert result["count"] == 1
    assert result["results"][0]["metadata"]["accession"] == "IPR000971"
    assert "interpro/api/entry/interpro/protein/uniprot/P69905" in captured["url"]
    await client.aclose()


@pytest.mark.asyncio
async def test_query_interpro_missing_accession_raises_value_error():
    adapters = StructureDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'accession'"):
        await adapters.query_interpro({})

    with pytest.raises(ValueError, match="non-empty 'accession'"):
        await adapters.query_interpro(None)


@pytest.mark.asyncio
async def test_query_interpro_204_returns_empty_results():
    client = _client(lambda r: httpx.Response(204))
    adapters = StructureDBAdapters(client)

    result = await adapters.query_interpro({"accession": "NOTREAL"})

    assert result == {
        "accession": "NOTREAL",
        "source_database": "interpro",
        "count": 0,
        "results": [],
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_query_interpro_404_raises_structure_api_error():
    client = _client(lambda r: httpx.Response(404, text="not found"))
    adapters = StructureDBAdapters(client)

    with pytest.raises(StructureAPIError, match="found no"):
        await adapters.query_interpro({"accession": "NOTREAL"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_interpro_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = StructureDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_interpro({"accession": "P69905"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_interpro_malformed_body_raises_structure_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = StructureDBAdapters(client)

    with pytest.raises(StructureAPIError, match="expected 'results' list"):
        await adapters.query_interpro({"accession": "P69905"})
    await client.aclose()


# --- query_pdb -----------------------------------------------------------


@pytest.mark.asyncio
async def test_query_pdb_string_query_builds_full_text_terminal_node():
    captured = {}

    def handler(request):
        import json as _json

        captured["body"] = _json.loads(request.content)
        return httpx.Response(
            200,
            json={"total_count": 2, "result_set": [{"identifier": "2UZ3", "score": 1.0}]},
        )

    client = _client(handler)
    adapters = StructureDBAdapters(client)

    result = await adapters.query_pdb({"query": "thymidine kinase"})

    assert result["total_count"] == 2
    assert result["result_set"][0]["identifier"] == "2UZ3"
    assert captured["body"]["query"] == {
        "type": "terminal",
        "service": "full_text",
        "parameters": {"value": "thymidine kinase"},
    }
    assert captured["body"]["return_type"] == "entry"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_pdb_dict_query_passed_through_verbatim():
    captured = {}
    direct_node = {
        "type": "terminal",
        "service": "sequence",
        "parameters": {"sequence_type": "protein", "value": "MVLSPADKTNVKAAWGKVGAHAGEYGAEA"},
    }

    def handler(request):
        import json as _json

        captured["body"] = _json.loads(request.content)
        return httpx.Response(200, json={"total_count": 0, "result_set": []})

    client = _client(handler)
    adapters = StructureDBAdapters(client)

    await adapters.query_pdb({"query": direct_node})

    assert captured["body"]["query"] == direct_node
    await client.aclose()


@pytest.mark.asyncio
async def test_query_pdb_missing_query_raises_value_error():
    adapters = StructureDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'query'"):
        await adapters.query_pdb({})

    with pytest.raises(ValueError, match="non-empty 'query'"):
        await adapters.query_pdb(None)

    with pytest.raises(ValueError, match="non-empty 'query'"):
        await adapters.query_pdb({"query": "   "})

    with pytest.raises(ValueError, match="non-empty 'query'"):
        await adapters.query_pdb({"query": {}})


@pytest.mark.asyncio
async def test_query_pdb_204_returns_zero_results():
    client = _client(lambda r: httpx.Response(204))
    adapters = StructureDBAdapters(client)

    result = await adapters.query_pdb({"query": "zzzznonexistentzzzz"})

    assert result == {"total_count": 0, "result_set": []}
    await client.aclose()


@pytest.mark.asyncio
async def test_query_pdb_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = StructureDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_pdb({"query": "thymidine kinase"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_pdb_malformed_body_raises_structure_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = StructureDBAdapters(client)

    with pytest.raises(StructureAPIError, match="expected 'result_set' list"):
        await adapters.query_pdb({"query": "thymidine kinase"})
    await client.aclose()


# --- query_pdb_identifiers -----------------------------------------------


@pytest.mark.asyncio
async def test_query_pdb_identifiers_success_returns_entries():
    captured_urls = []

    def handler(request):
        captured_urls.append(str(request.url))
        return httpx.Response(200, json={"rcsb_id": "4HHB", "struct": {"title": "hemoglobin"}})

    client = _client(handler)
    adapters = StructureDBAdapters(client)

    result = await adapters.query_pdb_identifiers({"identifiers": ["4hhb", "1crn"]})

    assert result["count"] == 2
    assert result["entries"][0]["pdb_id"] == "4HHB"
    assert result["entries"][0]["data"]["rcsb_id"] == "4HHB"
    assert result["entries"][1]["pdb_id"] == "1CRN"
    assert "structure" not in result["entries"][0]
    assert captured_urls == [
        "https://data.rcsb.org/rest/v1/core/entry/4HHB",
        "https://data.rcsb.org/rest/v1/core/entry/1CRN",
    ]
    await client.aclose()


@pytest.mark.asyncio
async def test_query_pdb_identifiers_accepts_single_string_identifier():
    client = _client(lambda r: httpx.Response(200, json={"rcsb_id": "1CRN"}))
    adapters = StructureDBAdapters(client)

    result = await adapters.query_pdb_identifiers({"identifiers": "1crn"})

    assert result["count"] == 1
    assert result["entries"][0]["pdb_id"] == "1CRN"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_pdb_identifiers_include_files_fetches_structure_text():
    def handler(request):
        url = str(request.url)
        if "data.rcsb.org" in url:
            return httpx.Response(200, json={"rcsb_id": "1CRN"})
        return httpx.Response(200, text="HEADER dummy\nATOM 1\n")

    client = _client(handler)
    adapters = StructureDBAdapters(client)

    result = await adapters.query_pdb_identifiers({"identifiers": ["1crn"], "include_files": True})

    assert "HEADER dummy" in result["entries"][0]["structure"]
    await client.aclose()


@pytest.mark.asyncio
async def test_query_pdb_identifiers_empty_identifiers_raises_value_error():
    adapters = StructureDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'identifiers'"):
        await adapters.query_pdb_identifiers({"identifiers": []})

    with pytest.raises(ValueError, match="non-empty 'identifiers'"):
        await adapters.query_pdb_identifiers({})


@pytest.mark.asyncio
async def test_query_pdb_identifiers_404_raises_structure_api_error():
    client = _client(lambda r: httpx.Response(404, json={"status": 404, "message": "not found"}))
    adapters = StructureDBAdapters(client)

    with pytest.raises(StructureAPIError, match="was not found"):
        await adapters.query_pdb_identifiers({"identifiers": ["9ZZZ"]})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_pdb_identifiers_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = StructureDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_pdb_identifiers({"identifiers": ["4HHB"]})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_pdb_identifiers_malformed_body_raises_structure_api_error():
    client = _client(lambda r: httpx.Response(200, text="not json"))
    adapters = StructureDBAdapters(client)

    with pytest.raises(StructureAPIError, match="expected entry data"):
        await adapters.query_pdb_identifiers({"identifiers": ["4HHB"]})
    await client.aclose()


# --- query_emdb ------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_emdb_success_returns_data_with_normalized_id():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"admin": {"title": "Drosophila melanogaster CMG complex"}},
        )

    client = _client(handler)
    adapters = StructureDBAdapters(client)

    result = await adapters.query_emdb({"emdb_id": "EMD-1832"})

    assert result["emdb_id"] == "EMD-1832"
    assert result["data"]["admin"]["title"] == "Drosophila melanogaster CMG complex"
    assert captured["url"] == "https://www.ebi.ac.uk/emdb/api/entry/1832"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_emdb_accepts_bare_numeric_id():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"admin": {"title": "x"}})

    client = _client(handler)
    adapters = StructureDBAdapters(client)

    result = await adapters.query_emdb({"emdb_id": "1832"})

    assert result["emdb_id"] == "EMD-1832"
    assert captured["url"] == "https://www.ebi.ac.uk/emdb/api/entry/1832"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_emdb_missing_id_raises_value_error():
    adapters = StructureDBAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'emdb_id'"):
        await adapters.query_emdb({})

    with pytest.raises(ValueError, match="non-empty 'emdb_id'"):
        await adapters.query_emdb(None)


@pytest.mark.asyncio
async def test_query_emdb_404_raises_structure_api_error():
    client = _client(lambda r: httpx.Response(404, text="not found"))
    adapters = StructureDBAdapters(client)

    with pytest.raises(StructureAPIError, match="was not found"):
        await adapters.query_emdb({"emdb_id": "EMD-9999999"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_emdb_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = StructureDBAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_emdb({"emdb_id": "EMD-1832"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_emdb_malformed_body_raises_structure_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = StructureDBAdapters(client)

    with pytest.raises(StructureAPIError, match="expected entry data"):
        await adapters.query_emdb({"emdb_id": "EMD-1832"})
    await client.aclose()


# --- register_structure_db_tools ------------------------------------------


@pytest.mark.asyncio
async def test_register_structure_db_tools_makes_all_six_tools_routable():
    def handler(request):
        url = str(request.url)
        if "rest.uniprot.org" in url:
            return httpx.Response(200, json={"results": [{"primaryAccession": "P01308"}]})
        if "alphafold.ebi.ac.uk" in url:
            return httpx.Response(200, json=[{"uniprotAccession": "P69905"}])
        if "interpro" in url:
            return httpx.Response(200, json={"count": 1, "results": [{"metadata": {}}]})
        if "search.rcsb.org" in url:
            return httpx.Response(200, json={"total_count": 1, "result_set": [{"identifier": "4HHB"}]})
        if "data.rcsb.org" in url:
            return httpx.Response(200, json={"rcsb_id": "4HHB"})
        if "emdb" in url:
            return httpx.Response(200, json={"admin": {"title": "x"}})
        return httpx.Response(500)

    client = _client(handler)
    registry = MCPServerRegistry()

    registered = register_structure_db_tools(registry, client)

    assert set(registered) == {
        "query_uniprot",
        "query_alphafold",
        "query_interpro",
        "query_pdb",
        "query_pdb_identifiers",
        "query_emdb",
    }
    assert set(registered).issubset(registry.registry.keys())

    uniprot_out = await registry.route("query_uniprot", {"query": "insulin"})
    assert "P01308" in uniprot_out

    alphafold_out = await registry.route("query_alphafold", {"qualifier": "P69905"})
    assert "P69905" in alphafold_out

    interpro_out = await registry.route("query_interpro", {"accession": "P69905"})
    assert "count" in interpro_out

    pdb_out = await registry.route("query_pdb", {"query": "hemoglobin"})
    assert "4HHB" in pdb_out

    pdb_ids_out = await registry.route("query_pdb_identifiers", {"identifiers": ["4HHB"]})
    assert "4HHB" in pdb_ids_out

    emdb_out = await registry.route("query_emdb", {"emdb_id": "EMD-1832"})
    assert "EMD-1832" in emdb_out

    await client.aclose()


@pytest.mark.asyncio
async def test_register_structure_db_tools_without_injected_client_uses_default_names():
    # No client injected -> StructureDBAdapters would build a real
    # httpx.AsyncClient per call. We only assert registration here (no real
    # network call is made in this test), matching how `bio_direct_adapters.py`'s
    # own registration-only tests work.
    registry = MCPServerRegistry()

    registered = register_structure_db_tools(registry)

    assert set(registered) == {
        "query_uniprot",
        "query_alphafold",
        "query_interpro",
        "query_pdb",
        "query_pdb_identifiers",
        "query_emdb",
    }
