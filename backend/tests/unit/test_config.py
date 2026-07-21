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


def test_qdrant_enabled_defaults_to_true():
    """RAG-MARKER: unlike Neo4j/Vault (gated on credential presence), Qdrant
    is always-on infra in this architecture -- default `True`."""
    assert Settings().QDRANT_ENABLED is True


def test_qdrant_enabled_can_be_disabled_via_env(monkeypatch):
    monkeypatch.setenv("QDRANT_ENABLED", "false")
    assert Settings().QDRANT_ENABLED is False


def test_qdrant_collection_has_a_default_name():
    assert Settings().QDRANT_COLLECTION == "osw_documents"


def test_marker_enabled_defaults_to_false():
    """RAG-MARKER: the heavy OCR-grade parser stays strictly opt-in."""
    assert Settings().MARKER_ENABLED is False


def test_marker_enabled_can_be_enabled_via_env(monkeypatch):
    monkeypatch.setenv("MARKER_ENABLED", "true")
    assert Settings().MARKER_ENABLED is True
