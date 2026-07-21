"""
Unit tests for `Settings` (`src/infrastructure/config.py`), production-hardening
phase: `ENV` moved from a bare `str` to a strict `Literal["development",
"staging", "production"]` so a typo'd deployment value fails LOUDLY at
`Settings()` construction time instead of silently matching
`jwt_auth.py`'s permissive "not production" dev branch (ephemeral JWT secret,
etc.) while the operator believes they configured a real production
deployment.
"""
import pytest
from pydantic import ValidationError

from src.infrastructure.config import Settings


def test_env_defaults_to_development():
    assert Settings().ENV == "development"


@pytest.mark.parametrize("value", ["development", "staging", "production"])
def test_env_accepts_every_documented_value(monkeypatch, value):
    monkeypatch.setenv("ENV", value)
    assert Settings().ENV == value


@pytest.mark.parametrize("typo", ["prod", "Production", "PRODUCTION", "prd", ""])
def test_env_rejects_unrecognized_values(monkeypatch, typo):
    monkeypatch.setenv("ENV", typo)
    with pytest.raises(ValidationError):
        Settings()


def test_log_level_defaults_to_info():
    assert Settings().LOG_LEVEL == "INFO"
