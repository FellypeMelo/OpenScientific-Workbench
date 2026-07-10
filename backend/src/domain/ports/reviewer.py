from typing import Protocol

from src.domain.entities.dag import DAGSnapshot
from src.domain.entities.review import ReviewVerdict


class ReviewerPort(Protocol):
    """Critic that approves or rejects a resolved DAG (RF-002).

    Implementations range from a deterministic numeric check (NumericReviewer) to
    an LLM-based critic; the use case only depends on this interface.
    """

    async def review(self, snapshot: DAGSnapshot) -> ReviewVerdict:
        ...
