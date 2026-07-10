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
