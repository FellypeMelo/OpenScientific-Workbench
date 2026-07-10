"""Biology tool adapters mapping MCP tool names to JSON-RPC methods (RF-004).

Registers UniProt/PDB/STRING tools into the MCPServerRegistry so the orchestrator
can route to them; each handler forwards its arguments to the remote server via
the JSON-RPC client.
"""
from typing import Any, Dict, List

from src.infrastructure.mcp.jsonrpc_client import JSONRPCMCPClient
from src.infrastructure.mcp.server_registry import MCPServerRegistry

#: MCP tool name -> remote JSON-RPC method name.
_BIO_TOOLS = {
    "get_uniprot_sequence": "uniprot.get_sequence",
    "get_pdb_structure": "pdb.get_structure",
    "get_string_interactions": "string.get_interactions",
}


def register_bio_tools(registry: MCPServerRegistry, rpc_client: JSONRPCMCPClient) -> List[str]:
    """Registers the bio tools and returns the registered tool names."""
    registered = []
    for tool_name, rpc_method in _BIO_TOOLS.items():
        registry.register_server(tool_name, _make_handler(rpc_client, rpc_method))
        registered.append(tool_name)
    return registered


def _make_handler(rpc_client: JSONRPCMCPClient, rpc_method: str):
    async def handler(arguments: Dict[str, Any]):
        return await rpc_client.call(rpc_method, arguments)

    return handler
