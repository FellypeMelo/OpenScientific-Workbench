import pytest
from uuid import uuid4
from src.domain.entities.agent_session import AgentSession

def test_session_creation_defaults():
    workspace_id = uuid4()
    session = AgentSession(workspace_id=workspace_id)
    assert session.workspace_id == workspace_id
    assert session.session_status == "INITIALIZING"
    assert session.dag_snapshot == {}
    assert session.provenance_log == []

def test_session_valid_transitions():
    workspace_id = uuid4()
    session = AgentSession(workspace_id=workspace_id)
    
    # INITIALIZING -> DAG_GENERATION
    session.transition_to("DAG_GENERATION")
    assert session.session_status == "DAG_GENERATION"
    
    # DAG_GENERATION -> EXECUTING_SANDBOX
    session.transition_to("EXECUTING_SANDBOX")
    assert session.session_status == "EXECUTING_SANDBOX"
    
    # EXECUTING_SANDBOX -> REVIEW_PENDING
    session.transition_to("REVIEW_PENDING")
    assert session.session_status == "REVIEW_PENDING"
    
    # REVIEW_PENDING -> SNAPSHOT_TAKEN
    session.transition_to("SNAPSHOT_TAKEN")
    assert session.session_status == "SNAPSHOT_TAKEN"

def test_session_invalid_transition_raises():
    workspace_id = uuid4()
    session = AgentSession(workspace_id=workspace_id)
    
    # Cannot go from INITIALIZING to SNAPSHOT_TAKEN directly
    with pytest.raises(ValueError, match="Invalid state transition"):
        session.transition_to("SNAPSHOT_TAKEN")
