"""RF-004: direct UniProt/RCSB PDB/STRING REST API adapters, tested against
httpx's built-in `MockTransport` (same pattern `test_mcp_jsonrpc_client.py`
uses) so no real network call/external mock server is needed while still
exercising the real HTTP request/response handling logic."""
import httpx
import pytest

from src.infrastructure.mcp.bio_direct_adapters import (
    BioAPIError,
    BioDirectAdapters,
    register_direct_bio_tools,
)
from src.infrastructure.mcp.server_registry import MCPServerRegistry


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- get_uniprot_sequence -----------------------------------------------


@pytest.mark.asyncio
async def test_get_uniprot_sequence_success_parses_sequence_and_length():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"sequence": {"value": "MVLSPADKTNVKAAWGKVGAHAGEYGAEALERMFLSFPTTKTYFPHF", "length": 47}},
        )

    client = _client(handler)
    adapters = BioDirectAdapters(client)

    result = await adapters.get_uniprot_sequence({"accession": "P69905"})

    assert result == {
        "accession": "P69905",
        "sequence": "MVLSPADKTNVKAAWGKVGAHAGEYGAEALERMFLSFPTTKTYFPHF",
        "length": 47,
    }
    assert captured["url"] == "https://rest.uniprot.org/uniprotkb/P69905.json"
    await client.aclose()


@pytest.mark.asyncio
async def test_get_uniprot_sequence_missing_accession_raises_value_error():
    adapters = BioDirectAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'accession'"):
        await adapters.get_uniprot_sequence({})

    with pytest.raises(ValueError, match="non-empty 'accession'"):
        await adapters.get_uniprot_sequence(None)


@pytest.mark.asyncio
async def test_get_uniprot_sequence_404_raises_bio_api_error():
    client = _client(lambda r: httpx.Response(404, json={"error": "not found"}))
    adapters = BioDirectAdapters(client)

    with pytest.raises(BioAPIError, match="was not found"):
        await adapters.get_uniprot_sequence({"accession": "NOTREAL"})
    await client.aclose()


@pytest.mark.asyncio
async def test_get_uniprot_sequence_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = BioDirectAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.get_uniprot_sequence({"accession": "P69905"})
    await client.aclose()


@pytest.mark.asyncio
async def test_get_uniprot_sequence_malformed_body_raises_bio_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = BioDirectAdapters(client)

    with pytest.raises(BioAPIError, match="expected sequence data"):
        await adapters.get_uniprot_sequence({"accession": "P69905"})
    await client.aclose()


# --- get_pdb_structure ----------------------------------------------------


@pytest.mark.asyncio
async def test_get_pdb_structure_success_returns_raw_pdb_text():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, text="HEADER    OXYGEN STORAGE/TRANSPORT\nATOM      1  N   VAL A   1\n")

    client = _client(handler)
    adapters = BioDirectAdapters(client)

    result = await adapters.get_pdb_structure({"pdb_id": "1crn"})

    assert result["pdb_id"] == "1CRN"
    assert result["format"] == "pdb"
    assert "HEADER" in result["content"]
    assert captured["url"] == "https://files.rcsb.org/download/1CRN.pdb"
    await client.aclose()


@pytest.mark.asyncio
async def test_get_pdb_structure_missing_id_raises_value_error():
    adapters = BioDirectAdapters(_client(lambda r: httpx.Response(200, text="")))

    with pytest.raises(ValueError, match="non-empty 'pdb_id'"):
        await adapters.get_pdb_structure({})


@pytest.mark.asyncio
async def test_get_pdb_structure_404_raises_bio_api_error():
    client = _client(lambda r: httpx.Response(404, text="not found"))
    adapters = BioDirectAdapters(client)

    with pytest.raises(BioAPIError, match="was not found"):
        await adapters.get_pdb_structure({"pdb_id": "9ZZZ"})
    await client.aclose()


@pytest.mark.asyncio
async def test_get_pdb_structure_empty_body_raises_bio_api_error():
    client = _client(lambda r: httpx.Response(200, text="   "))
    adapters = BioDirectAdapters(client)

    with pytest.raises(BioAPIError, match="empty structure file"):
        await adapters.get_pdb_structure({"pdb_id": "1CRN"})
    await client.aclose()


# --- get_string_interactions ----------------------------------------------


@pytest.mark.asyncio
async def test_get_string_interactions_success_returns_list():
    captured = {}

    def handler(request):
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json=[
                {"preferredName_A": "TP53", "preferredName_B": "MDM2", "score": 0.99},
            ],
        )

    client = _client(handler)
    adapters = BioDirectAdapters(client)

    result = await adapters.get_string_interactions({"identifiers": ["TP53", "MDM2"]})

    assert result == [{"preferredName_A": "TP53", "preferredName_B": "MDM2", "score": 0.99}]
    # Decoded query param value is the raw separator byte (carriage return);
    # on the wire this is the percent-encoded `%0D` STRING's API expects.
    assert captured["params"]["identifiers"] == "TP53\rMDM2"
    assert captured["params"]["species"] == "9606"
    await client.aclose()


@pytest.mark.asyncio
async def test_get_string_interactions_accepts_single_string_identifier():
    client = _client(
        lambda r: httpx.Response(200, json=[{"preferredName_A": "TP53", "preferredName_B": "TP53"}])
    )
    adapters = BioDirectAdapters(client)

    result = await adapters.get_string_interactions({"identifiers": "TP53"})

    assert len(result) == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_get_string_interactions_empty_identifiers_raises_value_error():
    adapters = BioDirectAdapters(_client(lambda r: httpx.Response(200, json=[])))

    with pytest.raises(ValueError, match="non-empty 'identifiers'"):
        await adapters.get_string_interactions({"identifiers": []})

    with pytest.raises(ValueError, match="non-empty 'identifiers'"):
        await adapters.get_string_interactions({})


@pytest.mark.asyncio
async def test_get_string_interactions_non_list_response_raises_bio_api_error():
    client = _client(lambda r: httpx.Response(200, json={"error": "malformed"}))
    adapters = BioDirectAdapters(client)

    with pytest.raises(BioAPIError, match="unexpected response shape"):
        await adapters.get_string_interactions({"identifiers": ["TP53"]})
    await client.aclose()


# --- register_direct_bio_tools --------------------------------------------


@pytest.mark.asyncio
async def test_register_direct_bio_tools_makes_all_three_tools_routable():
    def handler(request):
        if "uniprotkb" in str(request.url):
            return httpx.Response(200, json={"sequence": {"value": "MVLS", "length": 4}})
        if "files.rcsb.org" in str(request.url):
            return httpx.Response(200, text="HEADER dummy\n")
        if "string-db.org" in str(request.url):
            return httpx.Response(200, json=[{"a": "b"}])
        return httpx.Response(500)

    client = _client(handler)
    registry = MCPServerRegistry()

    registered = register_direct_bio_tools(registry, client)

    assert set(registered) == {"get_uniprot_sequence", "get_pdb_structure", "get_string_interactions"}
    assert set(registered).issubset(registry.registry.keys())

    seq_out = await registry.route("get_uniprot_sequence", {"accession": "P69905"})
    assert "MVLS" in seq_out

    pdb_out = await registry.route("get_pdb_structure", {"pdb_id": "1CRN"})
    assert "HEADER dummy" in pdb_out

    string_out = await registry.route("get_string_interactions", {"identifiers": ["TP53"]})
    assert "'a': 'b'" in string_out or '"a": "b"' in string_out

    await client.aclose()


@pytest.mark.asyncio
async def test_register_direct_bio_tools_without_injected_client_uses_default_names():
    # No client injected -> BioDirectAdapters would build a real
    # httpx.AsyncClient per call. We only assert registration here (no real
    # network call is made in this test), matching how `bio_adapters.py`'s own
    # registration-only tests work.
    registry = MCPServerRegistry()

    registered = register_direct_bio_tools(registry)

    assert set(registered) == {"get_uniprot_sequence", "get_pdb_structure", "get_string_interactions"}
