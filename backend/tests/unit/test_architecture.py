import pytest

def test_domain_user_import():
    """
    Test checking if the domain User entity can be imported.
    This should fail initially (RED) as the code has not been written yet.
    """
    from src.domain.entities.user import User
    assert User is not None
