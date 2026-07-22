"""
Additional coverage for `MCPServerRegistry.route()` beyond the basic
registered/unregistered cases already covered in `test_infrastructure_adapters.py`
and `test_mcp_jsonrpc.py`: argument passthrough, async handler support, and the
non-callable-handler error path.
"""
import pytest

from src.infrastructure.mcp.server_registry import MCPServerRegistry


@pytest.mark.asyncio
async def test_route_passes_arguments_through_to_registered_handler():
    registry = MCPServerRegistry()
    received = {}

    def handler(arguments):
        received.update(arguments)
        return "ok"

    registry.register_server("some_tool", handler)
    result = await registry.route("some_tool", {"a": 1, "b": "two"})

    assert result == "ok"
    assert received == {"a": 1, "b": "two"}


@pytest.mark.asyncio
async def test_route_supports_async_handlers():
    registry = MCPServerRegistry()

    async def async_handler(arguments):
        return f"async result for {arguments.get('x')}"

    registry.register_server("async_tool", async_handler)
    result = await registry.route("async_tool", {"x": 42})

    assert result == "async result for 42"


@pytest.mark.asyncio
async def test_route_raises_typeerror_for_non_callable_registered_value():
    registry = MCPServerRegistry()
    registry.register_server("broken_tool", "not_a_callable")

    with pytest.raises(TypeError, match="not callable"):
        await registry.route("broken_tool", {})


def test_register_server_stores_handler_in_registry():
    registry = MCPServerRegistry()

    def handler(arguments):
        return "unused"

    registry.register_server("my_tool", handler)
    assert registry.registry["my_tool"] is handler


@pytest.mark.asyncio
async def test_route_json_encodes_dict_results_instead_of_python_repr():
    """A handler returning a dict (every action-tool handler does) must come
    back as real JSON (double-quoted), not `str(dict)`'s single-quoted repr
    -- the latter is not valid JSON and unparseable by any consumer."""
    registry = MCPServerRegistry()
    registry.register_server("get_thing", lambda arguments: {"a": 1, "b": "two"})

    result = await registry.route("get_thing", {})

    assert result == '{"a": 1, "b": "two"}'
    import json
    assert json.loads(result) == {"a": 1, "b": "two"}


@pytest.mark.asyncio
async def test_route_json_encodes_list_results():
    registry = MCPServerRegistry()
    registry.register_server("get_list", lambda arguments: [{"id": 1}, {"id": 2}])

    result = await registry.route("get_list", {})

    import json
    assert json.loads(result) == [{"id": 1}, {"id": 2}]


@pytest.mark.asyncio
async def test_route_keeps_plain_str_coercion_for_non_dict_list_results():
    registry = MCPServerRegistry()
    registry.register_server("get_number", lambda arguments: 42)

    result = await registry.route("get_number", {})

    assert result == "42"
