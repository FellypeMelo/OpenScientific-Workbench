from pydantic import BaseModel


class ReviewVerdict(BaseModel):
    """Outcome of the actor-critic review of a resolved DAG (RF-002)."""

    approved: bool
    reason: str = ""
