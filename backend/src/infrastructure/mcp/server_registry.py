"""
MCP tool-call router adapter (Fase 4 - stop lying about unrouted tool calls).

Design notes:
- A full "real" implementation of this port would speak JSON-RPC over an
  SSE/STDIO transport to actual, separately-running MCP server processes
  (spawning/supervising subprocesses, a JSON-RPC client/session per server,
  reconnect/backoff logic, ...). That is a large scope explicitly out of
  reach for this pass (see `docs/planning/execution_plan_gap_closure.md`,
  Fase 4). Instead this is a smaller, honest fix: `route()` now actually
  consults `self.registry` (populated via `register_server()`) instead of
  pattern-matching `tool_name` and returning a hardcoded "success" string
  regardless of whether any server/handler was ever registered.
- If a handler is registered for `tool_name`, it is invoked (both sync and
  async callables are supported) and its result is returned. If nothing is
  registered, `route()` returns an explicit "not implemented" style message
  instead of a string that implies real execution happened -- callers can no
  longer mistake an unrouted tool call for one that actually ran somewhere.
"""
import inspect
from typing import Any, Callable, Dict

from src.domain.ports.mcp_router import MCPRouterPort


class MCPServerRegistry(MCPRouterPort):
    """
    Adapter implementing MCPRouterPort, managing local and remote MCP server
    handlers keyed by tool name.
    """
    def __init__(self):
        # tool_name -> handler. A handler is any callable (sync or async)
        # accepting the tool's `arguments` dict and returning a result.
        self.registry: Dict[str, Callable[[Dict[str, Any]], Any]] = {}

    def register_server(self, name: str, server_instance: Any) -> None:
        """Registers a handler for tool calls named `name`."""
        self.registry[name] = server_instance

    async def route(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        handler = self.registry.get(tool_name)
        if handler is None:
            return (
                f"MCP tool '{tool_name}' is not registered with this server registry; "
                "no local or remote MCP server handler is available to execute it. "
                "Register one via `register_server()` before routing calls to it."
            )

        if not callable(handler):
            raise TypeError(
                f"Registered handler for MCP tool '{tool_name}' is not callable: {handler!r}"
            )

        result = handler(arguments)
        if inspect.isawaitable(result):
            result = await result
        return str(result)
