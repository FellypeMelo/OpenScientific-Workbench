"""Unit tests for the actor-critic numeric reviewer (RF-002).

The reviewer reuses NumericValidator (<1e-5) to gate a completed DAG: a node
whose actor ``output`` diverges from the critic's ``expected`` value fails review.
"""
import pytest

from src.domain.entities.dag import DAGNode, DAGSnapshot
from src.domain.services.numeric_reviewer import NumericReviewer


@pytest.mark.asyncio
async def test_approves_when_output_within_tolerance():
    reviewer = NumericReviewer(tolerance=1e-5)
    snapshot = DAGSnapshot(
        nodes=[
            DAGNode(
                id="n1",
                description="dock",
                status="COMPLETED",
                output={"affinity_kd": -7.820001},
                expected={"affinity_kd": -7.820000},
            )
        ]
    )

    verdict = await reviewer.review(snapshot)

    assert verdict.approved is True


@pytest.mark.asyncio
async def test_rejects_when_output_diverges_beyond_tolerance():
    reviewer = NumericReviewer(tolerance=1e-5)
    snapshot = DAGSnapshot(
        nodes=[
            DAGNode(
                id="n1",
                description="dock",
                status="COMPLETED",
                output={"affinity_kd": -1.2200},
                expected={"affinity_kd": -7.8200},
            )
        ]
    )

    verdict = await reviewer.review(snapshot)

    assert verdict.approved is False
    assert "n1" in verdict.reason


@pytest.mark.asyncio
async def test_approves_when_no_numeric_assertions_present():
    reviewer = NumericReviewer()
    snapshot = DAGSnapshot(nodes=[DAGNode(id="n1", description="x", status="COMPLETED")])

    assert (await reviewer.review(snapshot)).approved is True
