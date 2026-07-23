"""Sandbox-backed implementation of ``NodeExecutorPort`` (RF-005/RNF-001/RNF-002).

Where ``LLMNodeExecutor`` (see ``infrastructure/llm/llm_node_executor.py``)
*asks the model to describe* what a step would do, ``SandboxNodeExecutor``
*actually runs* the node's ``language``/``command`` (populated by
``LLMTaskPlanner`` -- see ``infrastructure/llm/llm_task_planner.py``) inside a
real sandbox driver, and derives the node's reward from the process's real
exit code -- this is what RF-005 (real, isolated code execution) actually
requires; ``LLMNodeExecutor`` remains available as an explicit opt-out for
callers that don't want/need real execution (see
``presentation/routes/tasks.py``'s ``execution_mode`` field).

The driver is duck-typed (any object exposing ``execute_python_script``/
``execute_bash``/``execute_r_script``, each returning ``(stdout, exit_code)``)
-- in practice ``BubblewrapSandboxDriver`` (the real default) or
``GVisorSandboxDriver`` (dormant alternative), see
``infrastructure/sandbox/bubblewrap_driver.py``.
"""
import asyncio
import json
import logging
import os
import re
from typing import Optional

from src.domain.entities.dag import DAGNode
from src.domain.ports.mcp_router import MCPRouterPort

logger = logging.getLogger(__name__)

# Sanitizes a DAG node id into a safe filename component -- node ids come from
# an LLM's JSON response, so they are semi-trusted input, not attacker-opaque,
# but must never be trusted as a raw filesystem path segment either.
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")

# "tool" is not another script-interpreter language -- it is a typed call
# into the registered MCP tool catalog (`domain/ports/mcp_router.py`) instead
# of LLM-generated code. See `simulate()`'s `language == "tool"` branch and
# `LLMTaskPlanner`'s `tool_names` constructor arg.
_SUPPORTED_LANGUAGES = ("python", "bash", "r", "tool")


class SandboxNodeExecutor:
    """Concrete ``NodeExecutorPort`` that simulates a DAG node via a real
    sandbox driver.

    Reward convention (matches ``NodeExecutorPort``'s docstring): the
    sandboxed process's exit code decides success/failure -- ``0`` -> ``1.0``
    (COMPLETED), anything else (including a caught ``PermissionError``/
    ``OSError`` from the driver itself, e.g. a path-traversal violation, a
    missing/non-functional sandbox, or an unsupported/empty ``language``/
    ``command``) -> ``-1.0`` (PRUNED). ``node.output`` is populated either way
    so a caller/UI can inspect what actually ran.
    """

    def __init__(self, driver, mcp_router: Optional[MCPRouterPort] = None):
        self.driver = driver
        # Optional: only needed for `language == "tool"` nodes. Left `None`
        # by default so every existing caller/test that constructs this
        # class with just a driver keeps working unchanged; a `"tool"` node
        # reaching `simulate()` with no router configured is pruned with a
        # clear error rather than raising `AttributeError`.
        self.mcp_router = mcp_router

    async def simulate(self, node: DAGNode) -> float:
        language = (node.language or "").strip().lower()
        command = (node.command or "").strip()

        if not command:
            logger.warning("Node %s has no command to execute; pruning.", node.id)
            node.output = {"error": "Node has no command to execute."}
            return -1.0

        if language not in _SUPPORTED_LANGUAGES:
            logger.warning(
                "Node %s has unsupported language %r; pruning.", node.id, node.language
            )
            node.output = {"error": f"Unsupported language: {node.language!r}"}
            return -1.0

        if language == "tool":
            return await self._simulate_tool_call(node, command)

        try:
            # Every `execute_*` call below runs a real, blocking
            # `subprocess.run` (up to `driver.timeout_seconds`, 30s by
            # default) -- offloaded to a worker thread so a slow/near-timeout
            # sandboxed script doesn't stall this process's single asyncio
            # event loop (and every other concurrent request on it) for the
            # duration. `simulate()` itself is `async def`, so a plain
            # synchronous call here would do exactly that.
            if language == "python":
                script_path = self._materialize_python_script(node, command)
                stdout, exit_code = await asyncio.to_thread(
                    self.driver.execute_python_script, script_path
                )
            elif language == "r":
                stdout, exit_code = await asyncio.to_thread(self.driver.execute_r_script, command)
            else:  # "bash"
                stdout, exit_code = await asyncio.to_thread(self.driver.execute_bash, command)
        except (PermissionError, OSError) as exc:
            # A driver-side security violation (path traversal) or genuine
            # transport failure fails this node's simulation -- the
            # orchestrator prunes it (and everything depending on it) rather
            # than crashing the whole task, mirroring `LLMNodeExecutor`'s
            # provider-failure handling.
            logger.exception("Sandbox execution failed for node %s", node.id)
            node.output = {"error": str(exc)}
            return -1.0

        node.output = {"stdout": stdout, "exit_code": exit_code}
        return 1.0 if exit_code == 0 else -1.0

    async def _simulate_tool_call(self, node: DAGNode, command: str) -> float:
        """Handles a ``language == "tool"`` node: ``command`` is JSON
        ``{"tool_name": str, "arguments": dict}`` (the shape `LLMTaskPlanner`
        is instructed to emit when it picks a registered tool instead of
        generating code), routed through `MCPRouterPort.route()` -- the SAME
        registry `POST /api/v1/mcp/tools/call` uses, see
        `infrastructure/mcp/server_registry.py`. This is what lets the DAG
        orchestrator actually reach the bio/DB adapters and sandboxed action
        tools instead of only ever generating a script from scratch."""
        if self.mcp_router is None:
            logger.warning(
                "Node %s is a 'tool' node but no mcp_router was configured; pruning.",
                node.id,
            )
            node.output = {"error": "No MCP router configured for tool-call execution."}
            return -1.0

        try:
            payload = json.loads(command)
            tool_name = str(payload["tool_name"])
            arguments = payload.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise TypeError("'arguments' must be a JSON object")
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Node %s has a malformed tool-call command: %s", node.id, exc)
            node.output = {
                "error": (
                    "Malformed tool-call command; expected JSON "
                    f'{{"tool_name": ..., "arguments": {{...}}}}}}: {exc}'
                )
            }
            return -1.0

        try:
            result = await self.mcp_router.route(tool_name, arguments)
        except Exception as exc:  # noqa: BLE001 -- a failing tool call is a normal <0 reward outcome
            logger.exception("Tool call '%s' failed for node %s", tool_name, node.id)
            node.output = {"error": str(exc)}
            return -1.0

        node.output = {"tool_name": tool_name, "result": result}
        return 1.0

    def _materialize_python_script(self, node: DAGNode, source: str) -> str:
        """Writes ``node.command``'s Python source to a real file inside the
        driver's workspace and returns its path RELATIVE to that workspace, as
        ``execute_python_script`` expects (mirrors how a real research agent's
        generated script would land on disk before being sandboxed)."""
        workspace_root = getattr(self.driver, "workspace_root", "osw_workspace")
        os.makedirs(workspace_root, exist_ok=True)
        safe_id = _SAFE_ID_RE.sub("_", node.id).strip("_") or "node"
        filename = f"_dag_{safe_id}.py"
        with open(os.path.join(workspace_root, filename), "w", encoding="utf-8") as fh:
            fh.write(source)
        return filename
