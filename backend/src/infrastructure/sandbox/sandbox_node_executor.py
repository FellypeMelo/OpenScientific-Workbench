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
import logging
import os
import re

from src.domain.entities.dag import DAGNode

logger = logging.getLogger(__name__)

# Sanitizes a DAG node id into a safe filename component -- node ids come from
# an LLM's JSON response, so they are semi-trusted input, not attacker-opaque,
# but must never be trusted as a raw filesystem path segment either.
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")

_SUPPORTED_LANGUAGES = ("python", "bash", "r")


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

    def __init__(self, driver):
        self.driver = driver

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

        try:
            if language == "python":
                script_path = self._materialize_python_script(node, command)
                stdout, exit_code = self.driver.execute_python_script(script_path)
            elif language == "r":
                stdout, exit_code = self.driver.execute_r_script(command)
            else:  # "bash"
                stdout, exit_code = self.driver.execute_bash(command)
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
