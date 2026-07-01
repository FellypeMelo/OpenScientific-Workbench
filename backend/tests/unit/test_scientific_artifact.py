import pytest
from uuid import uuid4
from pydantic import ValidationError
from src.domain.entities.scientific_artifact import ScientificArtifact

def test_artifact_creation_valid():
    session_id = uuid4()
    valid_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" # SHA-256 for empty string
    artifact = ScientificArtifact(
        session_id=session_id,
        name="test_result.csv",
        sha256_hash=valid_hash
    )
    assert artifact.session_id == session_id
    assert artifact.name == "test_result.csv"
    assert artifact.sha256_hash == valid_hash

def test_artifact_creation_invalid_hash():
    session_id = uuid4()
    invalid_hashes = [
        "short",
        "nothexadecimalg3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855", # Uppercase is ok if we normalize, but let's assert strict matching depending on validator
    ]
    for h in invalid_hashes:
        with pytest.raises(ValidationError):
            ScientificArtifact(session_id=session_id, name="test.csv", sha256_hash=h)
