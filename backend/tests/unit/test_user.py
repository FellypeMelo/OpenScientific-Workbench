import pytest
from pydantic import ValidationError
from src.domain.entities.user import User

def test_user_creation_valid():
    user = User(email="scientist@osw.org")
    assert user.email == "scientist@osw.org"
    assert user.iam_role == "scientist"
    assert user.id is not None

def test_user_creation_invalid_email():
    with pytest.raises(ValidationError):
        User(email="invalid-email")

def test_user_creation_custom_role():
    user = User(email="admin@osw.org", iam_role="admin")
    assert user.iam_role == "admin"
