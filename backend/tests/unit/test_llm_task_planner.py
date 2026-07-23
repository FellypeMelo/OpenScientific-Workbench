"""Unit tests for the LLM-backed task planner (RF-001 infrastructure adapter).

The ModelProviderPort is faked, so no API keys / network are needed: we assert
that the planner turns the model's JSON answer into a valid DAGSnapshot.
"""
import json

import pytest

from src.domain.entities.dag import DAGSnapshot
from src.infrastructure.llm.llm_task_planner import LLMTaskPlanner


class FakeModel:
    def __init__(self, response: str):
        self._response = response
        self.prompts: list[tuple[str, str]] = []

    async def generate_response(self, prompt, system_instruction, temperature=0.0):
        self.prompts.append((prompt, system_instruction))
        return self._response

    def generate_stream(self, prompt, system_instruction, temperature=0.0):  # pragma: no cover
        raise NotImplementedError


@pytest.mark.asyncio
async def test_plan_parses_model_json_into_dag():
    resp = (
        '{"nodes": ['
        '{"id": "n1", "description": "load sequence data", "dependencies": []},'
        '{"id": "n2", "description": "run alignment", "dependencies": ["n1"]}'
        ']}'
    )
    planner = LLMTaskPlanner(FakeModel(resp))

    snapshot = await planner.plan("align these genes")

    assert isinstance(snapshot, DAGSnapshot)
    assert len(snapshot.nodes) == 2
    assert snapshot.get_node("n2").dependencies == ["n1"]
    assert all(n.reward is None and n.status == "PENDING" for n in snapshot.nodes)
    # Edge derived from the dependency.
    assert ("n1", "n2") in [tuple(e) for e in snapshot.edges]


@pytest.mark.asyncio
async def test_plan_extracts_json_wrapped_in_prose_and_fences():
    resp = 'Sure, here is the plan:\n```json\n[{"id": "a", "description": "x", "dependencies": []}]\n```\nDone.'
    planner = LLMTaskPlanner(FakeModel(resp))

    snapshot = await planner.plan("do x")

    assert len(snapshot.nodes) == 1
    assert snapshot.get_node("a").description == "x"


@pytest.mark.asyncio
async def test_plan_raises_when_no_json_present():
    planner = LLMTaskPlanner(FakeModel("I cannot help with that."))

    with pytest.raises(ValueError, match="plan"):
        await planner.plan("whatever")


@pytest.mark.asyncio
async def test_plan_parses_language_and_command_per_node():
    """RF-005: the planner must pass through the LLM's per-node `language`/
    `command` so `SandboxNodeExecutor` has something real to execute."""
    resp = (
        '{"nodes": ['
        '{"id": "n1", "description": "print 42", "dependencies": [], '
        '"language": "PYTHON", "command": "print(42)"},'
        '{"id": "n2", "description": "list files", "dependencies": ["n1"], '
        '"language": "bash", "command": "ls -la"}'
        ']}'
    )
    planner = LLMTaskPlanner(FakeModel(resp))

    snapshot = await planner.plan("compute and inspect")

    n1 = snapshot.get_node("n1")
    n2 = snapshot.get_node("n2")
    # Case-normalized to lowercase regardless of what the model emitted.
    assert n1.language == "python"
    assert n1.command == "print(42)"
    assert n2.language == "bash"
    assert n2.command == "ls -la"


@pytest.mark.asyncio
async def test_plan_defaults_language_and_command_when_omitted():
    """A model that doesn't emit `language`/`command` (e.g. an older prompt
    version, or a model that ignores the instruction) must not crash the
    planner -- `DAGNode` falls back to its own safe defaults."""
    resp = '{"nodes": [{"id": "a", "description": "x", "dependencies": []}]}'
    planner = LLMTaskPlanner(FakeModel(resp))

    snapshot = await planner.plan("do x")

    node = snapshot.get_node("a")
    assert node.language == "bash"
    assert node.command == ""


@pytest.mark.asyncio
async def test_system_instruction_omits_tool_language_when_no_tools_registered():
    model = FakeModel('{"nodes": [{"id": "a", "description": "x", "dependencies": []}]}')
    planner = LLMTaskPlanner(model)

    await planner.plan("do x")

    _, system_instruction = model.prompts[0]
    assert "No tools are currently registered" in system_instruction
    assert "never \"tool\"" in system_instruction


@pytest.mark.asyncio
async def test_system_instruction_lists_registered_tool_names():
    model = FakeModel('{"nodes": [{"id": "a", "description": "x", "dependencies": []}]}')
    planner = LLMTaskPlanner(model, tool_names=["get_uniprot_sequence", "docking_autodock_vina"])

    await planner.plan("dock this ligand")

    _, system_instruction = model.prompts[0]
    assert "get_uniprot_sequence" in system_instruction
    assert "docking_autodock_vina" in system_instruction
    assert '"tool"' in system_instruction


class FakeToolIndex:
    """`ToolCatalogIndex`-shaped double for retrieval tests below -- no real
    Qdrant/embedding involved, see `test_tool_catalog_index.py` for that."""

    def __init__(self, usable=True, results=None):
        self._usable = usable
        self._results = results or []
        self.queries: list[tuple[str, int]] = []

    @property
    def usable(self):
        return self._usable

    async def top_k(self, task_nl, k):
        self.queries.append((task_nl, k))
        return self._results


def _many_tool_names(n):
    return [f"tool_{i}" for i in range(n)]


@pytest.mark.asyncio
async def test_system_instruction_full_dump_below_retrieval_threshold_even_with_usable_index():
    model = FakeModel('{"nodes": [{"id": "a", "description": "x", "dependencies": []}]}')
    index = FakeToolIndex(usable=True, results=[("tool_1", "desc")])
    planner = LLMTaskPlanner(model, tool_names=_many_tool_names(5), tool_index=index)

    await planner.plan("do x")

    assert index.queries == []  # never consulted -- small catalog, full dump is fine
    _, system_instruction = model.prompts[0]
    assert "Registered tools you may call:" in system_instruction
    assert "tool_1" in system_instruction


@pytest.mark.asyncio
async def test_system_instruction_uses_retrieval_above_threshold_when_index_usable():
    model = FakeModel('{"nodes": [{"id": "a", "description": "x", "dependencies": []}]}')
    tool_names = _many_tool_names(40)
    index = FakeToolIndex(
        usable=True,
        results=[("tool_3", "does the thing"), ("tool_7", "does another thing")],
    )
    planner = LLMTaskPlanner(model, tool_names=tool_names, tool_index=index)

    await planner.plan("dock this ligand")

    assert index.queries == [("dock this ligand", 12)]
    _, system_instruction = model.prompts[0]
    assert "40 tools are registered in total" in system_instruction
    assert "tool_3 — does the thing" in system_instruction
    assert "tool_7 — does another thing" in system_instruction
    # The full 40-name dump must NOT also be present -- retrieval replaces it.
    assert "Registered tools you may call:" not in system_instruction


@pytest.mark.asyncio
async def test_system_instruction_falls_back_to_full_dump_when_index_not_usable():
    model = FakeModel('{"nodes": [{"id": "a", "description": "x", "dependencies": []}]}')
    tool_names = _many_tool_names(40)
    index = FakeToolIndex(usable=False, results=[("tool_3", "irrelevant, unusable")])
    planner = LLMTaskPlanner(model, tool_names=tool_names, tool_index=index)

    await planner.plan("dock this ligand")

    assert index.queries == []
    _, system_instruction = model.prompts[0]
    assert "Registered tools you may call:" in system_instruction


@pytest.mark.asyncio
async def test_system_instruction_falls_back_to_full_dump_when_retrieval_returns_nothing_usable():
    model = FakeModel('{"nodes": [{"id": "a", "description": "x", "dependencies": []}]}')
    tool_names = _many_tool_names(40)
    # Retrieval only returns names that are NOT in the registered set (stale
    # index) -- must be filtered out entirely, then fall back cleanly.
    index = FakeToolIndex(usable=True, results=[("renamed_or_removed_tool", "stale")])
    planner = LLMTaskPlanner(model, tool_names=tool_names, tool_index=index)

    await planner.plan("dock this ligand")

    _, system_instruction = model.prompts[0]
    assert "renamed_or_removed_tool" not in system_instruction
    assert "Registered tools you may call:" in system_instruction


@pytest.mark.asyncio
async def test_system_instruction_falls_back_to_full_dump_when_retrieval_raises():
    """`usable=True` only means "configured to try" -- a real connection
    failure (e.g. Qdrant unreachable) must degrade to the full dump, not
    propagate out of `plan()` and abort the whole task submission."""

    class RaisingToolIndex(FakeToolIndex):
        async def top_k(self, task_nl, k):
            raise ConnectionError("qdrant unreachable")

    model = FakeModel('{"nodes": [{"id": "a", "description": "x", "dependencies": []}]}')
    tool_names = _many_tool_names(40)
    planner = LLMTaskPlanner(model, tool_names=tool_names, tool_index=RaisingToolIndex())

    snapshot = await planner.plan("dock this ligand")

    assert len(snapshot.nodes) == 1  # plan() completed instead of raising
    _, system_instruction = model.prompts[0]
    assert "Registered tools you may call:" in system_instruction


@pytest.mark.asyncio
async def test_plan_parses_tool_language_node():
    resp = (
        '{"nodes": [{"id": "n1", "description": "fetch sequence", "dependencies": [], '
        '"language": "tool", "command": "{\\"tool_name\\": \\"get_uniprot_sequence\\", '
        '\\"arguments\\": {\\"accession\\": \\"P69905\\"}}"}]}'
    )
    planner = LLMTaskPlanner(FakeModel(resp), tool_names=["get_uniprot_sequence"])

    snapshot = await planner.plan("fetch a sequence")

    node = snapshot.get_node("n1")
    assert node.language == "tool"
    assert json.loads(node.command) == {
        "tool_name": "get_uniprot_sequence",
        "arguments": {"accession": "P69905"},
    }
