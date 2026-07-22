"""LLM-backed implementation of ``NodeExecutorPort`` (RF-001).

Executes (simulates) a single DAG sub-task node by asking a BYOK LLM to carry
out the concrete step described by the node, mirroring how ``LLMTaskPlanner``
(see ``llm_task_planner.py``) drives the same ``ModelProviderPort`` for the
*planning* half of the loop -- same "structured prompt over the existing,
already-tested `ModelProviderPort`" choice (KISS), no extra runtime.

The model's raw text answer is stored on ``node.output`` (wrapped as
``{"text": <answer>}`` so it fits ``DAGNode.output: Optional[Dict[str, Any]]``),
and a fixed reward is returned: ``1.0`` when the model responded (success ->
``MCTSOrchestrator`` marks the node COMPLETED), ``-1.0`` when the call itself
raised (failure -> PRUNED, mirroring the reward<0 pruning branch).

Known, deliberate scope boundary (see phase summary / RF-002 gap): this
executor does not populate ``node.expected``, so ``NumericReviewer`` (which
only gates when BOTH ``output`` and ``expected`` are set, see
``domain/services/numeric_reviewer.py``) never rejects live traffic yet -- an
independently-prompted second critic LLM call would be needed to populate
``expected``, which is out of scope for this wiring phase.
"""
import logging

from src.domain.entities.dag import DAGNode
from src.domain.ports.model_provider import ModelProviderPort

logger = logging.getLogger(__name__)

_SYSTEM_INSTRUCTION = (
    "You are a scientific research agent executing ONE concrete sub-task that "
    "is part of a larger research plan. Carry out the sub-task described by "
    "the user as best you can and report the result concisely and precisely. "
    "If you cannot complete the sub-task, say so explicitly and explain why."
)


class LLMNodeExecutor:
    """Concrete ``NodeExecutorPort`` that simulates a DAG node via an LLM."""

    def __init__(self, model: ModelProviderPort):
        self.model = model

    async def simulate(self, node: DAGNode) -> float:
        try:
            response = await self.model.generate_response(
                prompt=node.description,
                system_instruction=_SYSTEM_INSTRUCTION,
                temperature=0.0,
            )
        except Exception:
            # A provider-side failure (auth error, network error, malformed
            # response, etc.) is treated as this node failing its simulation --
            # the orchestrator prunes it (and everything depending on it)
            # rather than the whole task crashing.
            logger.exception("LLMNodeExecutor failed to execute node %s", node.id)
            return -1.0

        node.output = {"text": response}
        return 1.0
