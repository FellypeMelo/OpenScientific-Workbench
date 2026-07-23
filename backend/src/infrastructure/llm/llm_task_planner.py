"""LLM-backed implementation of ``TaskPlannerPort`` (RF-001).

Turns a natural-language research task into a DAG of sub-tasks by asking a BYOK
LLM (any ``ModelProviderPort``) for a strict JSON plan and parsing it into a
``DAGSnapshot``. We deliberately drive the existing, already-tested
``ModelProviderPort`` with a structured-JSON prompt instead of pulling in the
heavier ``pydantic-ai`` runtime -- same outcome (NL -> typed DAG), fewer moving
parts (KISS). The domain orchestrator depends only on the port, so this choice
is invisible to it.
"""

import logging
from typing import List, Optional

from src.domain.entities.dag import DAGNode, DAGSnapshot
from src.domain.ports.model_provider import ModelProviderPort
from src.domain.services.json_extraction import extract_json
from src.infrastructure.llm.tool_catalog_index import ToolCatalogIndex

logger = logging.getLogger(__name__)

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

    # Above this many registered tools, dumping every name (small catalogs)
    # stops being "fine" and starts diluting the prompt -- switch to
    # `tool_index` retrieval instead, when one was provided. Chosen well
    # above this repo's own test fixtures (2-3 tool names) so existing
    # full-dump behavior/tests are untouched, and well below the full
    # ~172-tool catalog (see `backend/docs/tools/`) that motivated this.
    _RETRIEVAL_THRESHOLD = 30

    def __init__(
        self,
        model: ModelProviderPort,
        tool_names: Optional[List[str]] = None,
        tool_index: Optional[ToolCatalogIndex] = None,
        retrieval_k: int = 12,
    ):
        self.model = model
        # Registered MCP tool names (bio/DB adapters + sandboxed action
        # tools, see `infrastructure/mcp/server_registry.py`) the planner may
        # emit `language: "tool"` nodes for. `None`/empty means "no tool
        # catalog available" -- the planner still works, it just never picks
        # "tool" (falls back to code-gen for everything, the pre-existing
        # behavior), rather than hallucinating a tool name that isn't real.
        self.tool_names = list(tool_names) if tool_names else []
        self._tool_name_set = set(self.tool_names)
        # Optional semantic retriever (`tool_catalog_index.ToolCatalogIndex`)
        # over the same tool catalog -- closes the "KNOWN SCALING LIMIT" this
        # docstring used to describe. `None`, or a not-yet-`usable` index
        # (mock Qdrant, e.g. CI/no live infra), means the planner falls back
        # to listing every tool name, same as before this existed.
        self.tool_index = tool_index
        self.retrieval_k = retrieval_k

    async def _build_system_instruction(self, task_nl: str) -> str:
        if not self.tool_names:
            return _BASE_SYSTEM_INSTRUCTION + (
                " No tools are currently registered -- always use \"python\", "
                '"bash", or "r", never "tool".'
            )
        if self.tool_index is not None and self.tool_index.usable and len(self.tool_names) > self._RETRIEVAL_THRESHOLD:
            try:
                retrieved = await self.tool_index.top_k(task_nl, self.retrieval_k)
            except Exception:
                # `usable` only reflects "configured to try" (see
                # `ToolCatalogIndex`/its Qdrant store's own docstrings), not
                # "actually reachable right now" -- a real connection failure
                # here must fall back to the full tool-name dump below, never
                # propagate up and abort planning over an optional
                # enhancement (mirrors `routes/chat.py`'s RAG-retrieval
                # fail-soft try/except around `RetrieveContextUseCase`).
                logger.warning(
                    "Tool retrieval failed; falling back to the full "
                    "registered-tool-name list.",
                    exc_info=True,
                )
                retrieved = []
            # Filter against `self.tool_names` (not just trust the index) in
            # case a `tool_index` built for a different/stale registry shape
            # got passed in -- never surface a "relevant tool" the DAG
            # executor can't actually route.
            top = [(name, description) for name, description in retrieved if name in self._tool_name_set]
            if top:
                catalog = "; ".join(f"{name} — {description}" for name, description in top)
                return _BASE_SYSTEM_INSTRUCTION + (
                    f" {len(self.tool_names)} tools are registered in total; the "
                    f"{len(top)} most relevant to this task are: {catalog}. Prefer "
                    "one of these if it fits the sub-task; fall back to "
                    '"python"/"bash"/"r" only if none of them do.'
                )
        catalog = ", ".join(sorted(self.tool_names))
        return _BASE_SYSTEM_INSTRUCTION + f" Registered tools you may call: {catalog}."

    async def plan(self, task_nl: str) -> DAGSnapshot:
        raw = await self.model.generate_response(
            prompt=task_nl,
            system_instruction=await self._build_system_instruction(task_nl),
            temperature=0.0,
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
