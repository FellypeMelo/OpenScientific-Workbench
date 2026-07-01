import pytest
from src.domain.ports.mcp_router import MCPRouterPort
from src.application.use_cases.route_mcp_tool import RouteMCPToolUseCase

class MockMCPRouter(MCPRouterPort):
    def __init__(self):
        self.routed_calls = []
    async def route(self, tool_name: str, arguments: dict) -> str:
        self.routed_calls.append((tool_name, arguments))
        if tool_name == "execute_sandbox_python":
            return "Execution complete. Output: 42"
        return "Unknown tool output"

@pytest.mark.asyncio
async def test_route_mcp_tool_success():
    router = MockMCPRouter()
    use_case = RouteMCPToolUseCase(router=router)

    result = await use_case.execute(
        tool_name="execute_sandbox_python",
        arguments={"script_content": "print(42)"}
    )

    assert result == "Execution complete. Output: 42"
    assert len(router.routed_calls) == 1
    assert router.routed_calls[0] == ("execute_sandbox_python", {"script_content": "print(42)"})

@pytest.mark.asyncio
async def test_route_mcp_tool_empty_name_fails():
    router = MockMCPRouter()
    use_case = RouteMCPToolUseCase(router=router)

    with pytest.raises(ValueError, match="Tool name cannot be empty"):
        await use_case.execute(tool_name="", arguments={})
