"""RF-004: real JSON-RPC 2.0 transport + bio tool registration, tested against
httpx's built-in MockTransport (no external mock server)."""
import json

import httpx
import pytest

from src.infrastructure.mcp.bio_adapters import register_bio_tools
from src.infrastructure.mcp.jsonrpc_client import JSONRPCError, JSONRPCMCPClient
from src.infrastructure.mcp.server_registry import MCPServerRegistry


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_call_posts_valid_envelope_and_parses_result():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": captured["body"]["id"], "result": {"sequence": "MVLS"}}
        )

    client = _client(handler)
    rpc = JSONRPCMCPClient("https://bio.example/rpc", client=client)

    result = await rpc.call("get_uniprot_sequence", {"accession": "P69905"})

    assert result == {"sequence": "MVLS"}
    body = captured["body"]
    assert body["jsonrpc"] == "2.0"
    assert body["method"] == "get_uniprot_sequence"
    assert body["params"] == {"accession": "P69905"}
    assert isinstance(body["id"], int)
    await client.aclose()


@pytest.mark.asyncio
async def test_call_raises_on_jsonrpc_error():
    def handler(request):
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}},
        )

    client = _client(handler)
    rpc = JSONRPCMCPClient("https://bio.example/rpc", client=client)

    with pytest.raises(JSONRPCError, match="Method not found"):
        await rpc.call("does_not_exist")
    await client.aclose()


@pytest.mark.asyncio
async def test_registered_bio_tool_routes_through_jsonrpc():
    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": f"OK:{body['method']}"})

    client = _client(handler)
    rpc = JSONRPCMCPClient("https://bio.example/rpc", client=client)
    registry = MCPServerRegistry()

    registered = register_bio_tools(registry, rpc)
    assert "get_uniprot_sequence" in registered

    out = await registry.route("get_uniprot_sequence", {"accession": "P69905"})
    assert "OK:uniprot.get_sequence" in out  # resolved, not the "not registered" fallback
    await client.aclose()
