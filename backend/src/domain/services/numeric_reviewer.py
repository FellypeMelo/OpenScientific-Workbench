"""Actor-critic numeric reviewer (RF-002).

Gates a resolved DAG by re-checking every completed node that carries both an
actor ``output`` and a critic-supplied ``expected`` value: if any pair diverges
beyond the tolerance (default 1e-5, via NumericValidator), the review is
rejected. Nodes without numeric assertions do not gate the result.
"""
from src.domain.entities.dag import DAGSnapshot
from src.domain.entities.review import ReviewVerdict
from src.domain.services.numeric_validator import NumericValidator


class NumericReviewer:
    def __init__(self, tolerance: float = 1e-5):
        self.validator = NumericValidator(tolerance=tolerance)

    async def review(self, snapshot: DAGSnapshot) -> ReviewVerdict:
        for node in snapshot.nodes:
            if node.status != "COMPLETED":
                continue
            if node.output is None or node.expected is None:
                continue
            if not self.validator.compare_structures(node.output, node.expected):
                return ReviewVerdict(
                    approved=False,
                    reason=f"Numeric divergence at node {node.id}: "
                    f"{node.output} vs expected {node.expected} (tol={self.validator.tolerance}).",
                )
        return ReviewVerdict(approved=True, reason="All numeric assertions within tolerance.")
