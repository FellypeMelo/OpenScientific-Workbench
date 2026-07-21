"""
Unit tests for `get_current_user_id` (`src/presentation/dependencies.py`),
the IDOR-fix dependency every route now uses to resolve "who is asking" from
the authenticated JWT claims instead of any client-supplied identifier.

Uses a minimal duck-typed stand-in for `fastapi.Request` (only `.state` is
read by the function under test) rather than constructing a real Starlette
`Request` -- this is a focused unit test of the dependency's own logic, not
an HTTP-transport test (that coverage lives in `test_idor_ownership.py` and
`test_presentation_routes.py`, exercised through real routes).
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.presentation.dependencies import get_current_user_id


def _fake_request(user=None) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(user=user) if user is not None else SimpleNamespace())


def test_returns_the_sub_claim_as_a_string():
    request = _fake_request(user={"sub": "11111111-1111-1111-1111-111111111111", "iam_role": "scientist"})
    assert get_current_user_id(request) == "11111111-1111-1111-1111-111111111111"


def test_raises_401_when_state_has_no_user_attribute_at_all():
    request = _fake_request(user=None)
    with pytest.raises(HTTPException) as exc_info:
        get_current_user_id(request)
    assert exc_info.value.status_code == 401


def test_raises_401_when_user_claims_are_missing_sub():
    request = _fake_request(user={"iam_role": "scientist"})
    with pytest.raises(HTTPException) as exc_info:
        get_current_user_id(request)
    assert exc_info.value.status_code == 401


def test_raises_401_when_user_is_not_a_dict():
    request = SimpleNamespace(state=SimpleNamespace(user="not-a-dict"))
    with pytest.raises(HTTPException) as exc_info:
        get_current_user_id(request)
    assert exc_info.value.status_code == 401
