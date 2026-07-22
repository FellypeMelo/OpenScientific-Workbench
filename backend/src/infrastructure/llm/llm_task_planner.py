"""LLM-backed implementation of ``TaskPlannerPort`` (RF-001).

Turns a natural-language research task into a DAG of sub-tasks by asking a BYOK
LLM (any ``ModelProviderPort``) for a strict JSON plan and parsing it into a
``DAGSnapshot``. We deliberately drive the existing, already-tested
``ModelProviderPort`` with a structured-JSON prompt instead of pulling in the
heavier ``pydantic-ai`` runtime -- same outcome (NL -> typed DAG), fewer moving
parts (KISS). The domain orchestrator depends only on the port, so this choice
is invisible to it.
"""

from src.domain.entities.dag import DAGNode, DAGSnapshot
from src.domain.ports.model_provider import ModelProviderPort
from src.domain.services.json_extraction import extract_json

_SYSTEM_INSTRUCTION = (
    "You are a scientific research planner. Decompose the user's task into a "
    "directed acyclic graph of concrete sub-tasks. Respond with ONLY a JSON "
    'object of the form {"nodes": [{"id": "n1", "description": "...", '
    '"dependencies": [], "language": "python", "command": "..."}, ...]}. '
    "Every dependency must reference another node id. `language` MUST be "
    'exactly one of "python", "bash", or "r" -- the interpreter a sandbox '
    "will run this node's `command` in. `command` MUST be the literal, "
    "directly-executable code that carries out the sub-task: for \"python\", "
    "the full source of a self-contained script (no external files assumed); "
    "for \"bash\", a single shell command line; for \"r\", an R "
    "expression/script. Do not include any prose outside the JSON."
)


class LLMTaskPlanner:
    """Concrete ``TaskPlannerPort`` that expands NL tasks via an LLM."""

    def __init__(self, model: ModelProviderPort):
        self.model = model

    async def plan(self, task_nl: str) -> DAGSnapshot:
        raw = await self.model.generate_response(
            prompt=task_nl, system_instruction=_SYSTEM_INSTRUCTION, temperature=0.0
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
