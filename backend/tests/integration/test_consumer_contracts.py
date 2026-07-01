import pytest
from pydantic import BaseModel, ValidationError

class CreateSessionContract(BaseModel):
    user_id: str
    workspace_id: str

def test_frontend_gateway_contract_compliance():
    # Valid contract format matches expected schemas
    valid_payload = {
        "user_id": "00000000-0000-0000-0000-000000000000",
        "workspace_id": "00000000-0000-0000-0000-000000000000"
    }
    
    contract = CreateSessionContract(**valid_payload)
    assert contract.user_id == "00000000-0000-0000-0000-000000000000"

    # Invalid contract payloads must fail parsing to prevent breaking integration
    invalid_payload = {
        "user_id": 12345, # Should be a UUID string
        "workspace_id": None
    }
    
    with pytest.raises(ValidationError):
        CreateSessionContract(**invalid_payload)
