import math
from typing import Any

class NumericValidator:
    """
    Domain service responsible for verifying mathematical consistency and detecting LLM numerical hallucinations.
    Ensures that floating point numbers match within a strict absolute tolerance.
    """
    
    def __init__(self, tolerance: float = 1e-5):
        self.tolerance = tolerance

    def compare_floats(self, val_a: float, val_b: float) -> bool:
        """
        Compares two floats and returns True if absolute difference is strictly within tolerance.
        """
        return math.isclose(val_a, val_b, abs_tol=self.tolerance)

    def compare_structures(self, struct_a: Any, struct_b: Any) -> bool:
        """
        Recursively compares nested dicts and lists, checking any floats against tolerance limit.
        """
        if type(struct_a) != type(struct_b):
            return False

        if isinstance(struct_a, dict):
            if set(struct_a.keys()) != set(struct_b.keys()):
                return False
            return all(self.compare_structures(struct_a[k], struct_b[k]) for k in struct_a)

        elif isinstance(struct_a, (list, tuple)):
            if len(struct_a) != len(struct_b):
                return False
            return all(self.compare_structures(val_a, val_b) for val_a, val_b in zip(struct_a, struct_b))

        elif isinstance(struct_a, float):
            return self.compare_floats(struct_a, struct_b)

        else:
            return struct_a == struct_b
