from typing import Dict, Any
from src.domain.ports.mcp_router import MCPRouterPort

class RouteMCPToolUseCase:
    """
    Application use case for executing semantic tool calls routed via the Model Context Protocol (MCP).
    """
    def __init__(self, router: MCPRouterPort):
        self.router = router

    async def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        # 1. Validate tool name
        if not tool_name or not tool_name.strip():
            raise ValueError("Tool name cannot be empty: A valid MCP tool name is required.")

        # 2. Route the tool call via MCP
        result = await self.router.route(tool_name, arguments)
        return result
