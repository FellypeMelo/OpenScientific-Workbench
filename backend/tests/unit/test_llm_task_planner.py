"""Unit tests for the LLM-backed task planner (RF-001 infrastructure adapter).

The ModelProviderPort is faked, so no API keys / network are needed: we assert
that the planner turns the model's JSON answer into a valid DAGSnapshot.
"""
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
