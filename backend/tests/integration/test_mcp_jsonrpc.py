import pytest
import json
from src.infrastructure.mcp.server_registry import MCPServerRegistry

@pytest.mark.asyncio
async def test_mcp_jsonrpc_roundtrip():
    registry = MCPServerRegistry()
    
    # Simulate a JSON-RPC 2.0 tool call request
    jsonrpc_request = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "execute_sandbox_python",
            "arguments": {
                "script_content": "import math\nprint(math.sqrt(16))"
            }
        },
        "id": 1
    }
    
    # Route the request
    tool_name = jsonrpc_request["params"]["name"]
    arguments = jsonrpc_request["params"]["arguments"]
    
    result_str = await registry.route(tool_name, arguments)
    
    # Build JSON-RPC 2.0 response format
    jsonrpc_response = {
        "jsonrpc": "2.0",
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": result_str
                }
            ]
        },
        "id": jsonrpc_request["id"]
    }
    
    assert jsonrpc_response["jsonrpc"] == "2.0"
    assert jsonrpc_response["id"] == 1
    assert "Processed script successfully" in jsonrpc_response["result"]["content"][0]["text"]
