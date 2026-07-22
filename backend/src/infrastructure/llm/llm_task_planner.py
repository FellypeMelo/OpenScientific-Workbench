"""LLM-backed implementation of ``TaskPlannerPort`` (RF-001).

Turns a natural-language research task into a DAG of sub-tasks by asking a BYOK
LLM (any ``ModelProviderPort``) for a strict JSON plan and parsing it into a
``DAGSnapshot``. We deliberately drive the existing, already-tested
``ModelProviderPort`` with a structured-JSON prompt instead of pulling in the
heavier ``pydantic-ai`` runtime -- same outcome (NL -> typed DAG), fewer moving
parts (KISS). The domain orchestrator depends only on the port, so this choice
is invisible to it.
"""

from typing import List, Optional

from src.domain.entities.dag import DAGNode, DAGSnapshot
from src.domain.ports.model_provider import ModelProviderPort
from src.domain.services.json_extraction import extract_json

_BASE_SYSTEM_INSTRUCTION = (
    "You are a scientific research planner. Decompose the user's task into a "
    "directed acyclic graph of concrete sub-tasks. Respond with ONLY a JSON "
    'object of the form {"nodes": [{"id": "n1", "description": "...", '
    '"dependencies": [], "language": "python", "command": "..."}, ...]}. '
    "Every dependency must reference another node id. `language` MUST be "
    'exactly one of "python", "bash", "r", or "tool". For "python"/"bash"/"r", '
    "`command` MUST be the literal, directly-executable code that carries out "
    "the sub-task: for \"python\", the full source of a self-contained script "
    "(no external files assumed); for \"bash\", a single shell command line; "
    "for \"r\", an R expression/script. For \"tool\", `command` MUST instead be "
    'a JSON string (not code) of the exact form {"tool_name": "...", '
    '"arguments": {...}} naming ONE of the registered tools listed below and '
    "its call arguments -- prefer \"tool\" over \"python\"/\"bash\" code-gen "
    "whenever a listed tool already does what the sub-task needs, instead of "
    "reimplementing it from scratch. Do not include any prose outside the JSON."
)


class LLMTaskPlanner:
    """Concrete ``TaskPlannerPort`` that expands NL tasks via an LLM."""

    def __init__(self, model: ModelProviderPort, tool_names: Optional[List[str]] = None):
        self.model = model
        # Registered MCP tool names (bio/DB adapters + sandboxed action
        # tools, see `infrastructure/mcp/server_registry.py`) the planner may
        # emit `language: "tool"` nodes for. `None`/empty means "no tool
        # catalog available" -- the planner still works, it just never picks
        # "tool" (falls back to code-gen for everything, the pre-existing
        # behavior), rather than hallucinating a tool name that isn't real.
        self.tool_names = list(tool_names) if tool_names else []

    @property
    def _system_instruction(self) -> str:
        # KNOWN SCALING LIMIT: this lists every registered tool name in every
        # planning prompt. Fine at dozens of tools; once the full ~170-tool
        # catalog (see `backend/docs/tools/`) is registered, this should
        # become a semantic retrieval step (embed `task_nl`, return the
        # top-K closest tool descriptions) instead of dumping the whole
        # catalog -- exactly what the Biomni paper's "prompt-based retriever"
        # does, and what this constructor does NOT implement yet. Left as a
        # follow-up rather than silently degrading prompt quality unnoticed.
        if not self.tool_names:
            return _BASE_SYSTEM_INSTRUCTION + (
                " No tools are currently registered -- always use \"python\", "
                '"bash", or "r", never "tool".'
            )
        catalog = ", ".join(sorted(self.tool_names))
        return _BASE_SYSTEM_INSTRUCTION + f" Registered tools you may call: {catalog}."

    async def plan(self, task_nl: str) -> DAGSnapshot:
        raw = await self.model.generate_response(
            prompt=task_nl, system_instruction=self._system_instruction, temperature=0.0
        )
        try:
            payload = extract_json(raw)
        except ValueError as exc:
            raise ValueError("Task planner response contained no parseable JSON plan.") from exc
        node_dicts = payload.get("nodes") if isinstance(payload, dict) else payload
        if not isinstance(node_dicts, list) or not node_dicts:
            raise ValueError("Task planner returned an empty or non-list plan.")

        nodes = [
            DAGNode(
                id=str(nd["id"]),
                description=str(nd.get("description", "")),
                dependencies=[str(d) for d in nd.get("dependencies", [])],
                language=str(nd.get("language", "bash")).strip().lower(),
                command=str(nd.get("command", "")),
            )
            for nd in node_dicts
        ]
        edges = [(dep, node.id) for node in nodes for dep in node.dependencies]
        return DAGSnapshot(nodes=nodes, edges=edges)
