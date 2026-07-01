from uuid import UUID, uuid4
from typing import Dict, Any, List
from pydantic import BaseModel, Field

class AgentSession(BaseModel):
    """
    Domain entity representing a long-running research agent session.
    """
    id: UUID = Field(default_factory=uuid4)
    workspace_id: UUID
    session_status: str = "INITIALIZING"
    dag_snapshot: Dict[str, Any] = Field(default_factory=dict)
    provenance_log: List[Dict[str, Any]] = Field(default_factory=list)

    # Valid transitions dictionary
    _VALID_TRANSITIONS: Dict[str, List[str]] = {
        "INITIALIZING": ["DAG_GENERATION"],
        "DAG_GENERATION": ["EXECUTING_SANDBOX", "EXECUTING_HPC", "SNAPSHOT_TAKEN"],
        "EXECUTING_SANDBOX": ["REVIEW_PENDING"],
        "EXECUTING_HPC": ["REVIEW_PENDING"],
        "REVIEW_PENDING": ["SNAPSHOT_TAKEN", "ARTIFACT_REJECTED"],
        "ARTIFACT_REJECTED": ["DAG_GENERATION"],
        "SNAPSHOT_TAKEN": ["DAG_GENERATION"]
    }

    def transition_to(self, new_status: str) -> None:
        """
        Safely transitions the session status to a new state if valid.
        Raises ValueError if transition is invalid.
        """
        allowed = self._VALID_TRANSITIONS.get(self.session_status, [])
        if new_status not in allowed:
            raise ValueError(
                f"Invalid state transition: Cannot transition from '{self.session_status}' to '{new_status}'."
            )
        self.session_status = new_status
