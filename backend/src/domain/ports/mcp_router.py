from typing import Protocol, Any, Dict

class MCPRouterPort(Protocol):
    """
    Domain port interface for routing tool calls via the Model Context Protocol (MCP).
    """
    async def route(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Routes a tool call JSON-RPC request to the respective local or remote server."""
        ...
