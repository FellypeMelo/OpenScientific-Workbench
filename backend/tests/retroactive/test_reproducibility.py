import pytest
import hashlib
import os

def calculate_protein_score(seq: str, weight: float) -> str:
    """Deterministic calculation utility."""
    # Ensure reproducible score formatting
    raw_str = f"{seq}_{weight:.6f}"
    return hashlib.sha256(raw_str.encode()).hexdigest()

def test_scientific_calculation_determinism():
    seq = "MTEYKLVVVGAGGVGKSALTIQLIQNHFVDEYDPTIEDSYRKQVVIDGETCLLDILDTAGQEE"
    weight = 7.820000
    
    hash_run_1 = calculate_protein_score(seq, weight)
    hash_run_2 = calculate_protein_score(seq, weight)
    
    # Assert exact determinism for audit trailing
    assert hash_run_1 == hash_run_2
    assert len(hash_run_1) == 64

def test_uv_lockfile_exists_for_reproducible_dependencies():
    # Verify that the package manager lock file exists
    assert os.path.exists("uv.lock") is True
