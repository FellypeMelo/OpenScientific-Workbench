import pytest
from src.domain.services.numeric_validator import NumericValidator

def test_validate_scalar_floats_pass():
    validator = NumericValidator(tolerance=1e-5)
    # Erro absoluto < 1e-5
    assert validator.compare_floats(-7.820001, -7.820000) is True
    assert validator.compare_floats(0.0000001, 0.0) is True

def test_validate_scalar_floats_fail():
    validator = NumericValidator(tolerance=1e-5)
    # Erro absoluto >= 1e-5
    assert validator.compare_floats(-1.2200, -7.8200) is False
    assert validator.compare_floats(1.00002, 1.0) is False

def test_validate_nested_structures():
    validator = NumericValidator(tolerance=1e-5)
    
    struct_a = {
        "metrics": [0.81, -7.820001, {"value": 1.2300001}]
    }
    struct_b = {
        "metrics": [0.81, -7.820000, {"value": 1.2300000}]
    }
    struct_c = {
        "metrics": [0.81, -7.820000, {"value": 1.24}] # Diverges at third index dict
    }
    
    assert validator.compare_structures(struct_a, struct_b) is True
    assert validator.compare_structures(struct_a, struct_c) is False
