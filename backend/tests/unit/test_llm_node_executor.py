"""Unit tests for the LLM-backed node executor (RF-001 infrastructure adapter).

The ModelProviderPort is faked, so no API keys / network are needed: we assert
the reward convention (>=0 success / <0 failure) and that a successful call
writes the model's answer onto ``node.output``.
"""
import pytest

from src.domain.entities.dag import DAGNode
from src.infrastructure.llm.llm_node_executor import LLMNodeExecutor


class FakeModel:
    def __init__(self, response: str = None, error: Exception = None):
        self._response = response
        self._error = error
        self.prompts: list[tuple[str, str]] = []

    async def generate_response(self, prompt, system_instruction, temperature=0.0):
        self.prompts.append((prompt, system_instruction))
        if self._error is not None:
            raise self._error
        return self._response

    def generate_stream(self, prompt, system_instruction, temperature=0.0):  # pragma: no cover
        raise NotImplementedError


@pytest.mark.asyncio
async def test_simulate_returns_positive_reward_and_sets_output_on_success():
    model = FakeModel(response="Alignment complete: 98% identity.")
    executor = LLMNodeExecutor(model)
    node = DAGNode(id="n1", description="Align reads to reference genome", dependencies=[])

    reward = await executor.simulate(node)

    assert reward == 1.0
    assert node.output == {"text": "Alignment complete: 98% identity."}
    # The node's own description drives the prompt, mirroring LLMTaskPlanner's
    # "task_nl becomes the prompt" convention.
    assert model.prompts[0][0] == "Align reads to reference genome"


@pytest.mark.asyncio
async def test_simulate_returns_negative_reward_and_leaves_output_none_on_provider_failure():
    model = FakeModel(error=RuntimeError("provider unavailable"))
    executor = LLMNodeExecutor(model)
    node = DAGNode(id="n1", description="Predict protein folding", dependencies=[])

    reward = await executor.simulate(node)

    assert reward == -1.0
    assert node.output is None


@pytest.mark.asyncio
async def test_simulate_does_not_set_expected_scope_boundary():
    """Deliberate scope boundary (see module docstring): this executor never
    populates `node.expected`, so NumericReviewer cannot gate on it yet."""
    model = FakeModel(response="ok")
    executor = LLMNodeExecutor(model)
    node = DAGNode(id="n1", description="do x", dependencies=[])

    await executor.simulate(node)

    assert node.expected is None
