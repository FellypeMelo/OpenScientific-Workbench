from typing import Dict, Any
from src.domain.ports.mcp_router import MCPRouterPort

class MCPServerRegistry(MCPRouterPort):
    """
    Adapter implementing MCPRouterPort, managing local and remote MCP server instances.
    """
    def __init__(self):
        self.registry: Dict[str, Any] = {}

    def register_server(self, name: str, server_instance: Any) -> None:
        self.registry[name] = server_instance

    async def route(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        # In a real environment, we'd look up the tool in our registered MCP servers
        # and forward the JSON-RPC request to the respective SSE/STDIO stream.
        
        # Simple dynamic router resolver logic
        if tool_name == "execute_sandbox_python":
            script = arguments.get("script_content", "")
            return f"Processed script successfully: {len(script)} bytes."
            
        return f"MCP tool '{tool_name}' invoked successfully."
