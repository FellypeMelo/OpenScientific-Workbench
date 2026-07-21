"""Unit tests for `get_mcp_registry` (`presentation/dependencies.py`,
RF-004/RF-009 gap closure): the lazy process-wide `MCPServerRegistry`
singleton that registers the direct bio-tool adapters by default, plus any
reproducible compiled Skills discovered under `settings.SKILLS_ROOT`.

Each test resets the module-level `_mcp_registry` singleton via monkeypatch
before/after so tests don't leak state into each other (or into other test
modules importing the same `dependencies` module).
"""
import pytest

from src.infrastructure.mcp.server_registry import MCPServerRegistry
from src.presentation import dependencies


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch):
    monkeypatch.setattr(dependencies, "_mcp_registry", None)
    yield
    monkeypatch.setattr(dependencies, "_mcp_registry", None)


def test_get_mcp_registry_returns_a_registry_instance():
    registry = dependencies.get_mcp_registry()
    assert isinstance(registry, MCPServerRegistry)


def test_get_mcp_registry_registers_direct_bio_tools_by_default():
    registry = dependencies.get_mcp_registry()
    assert "get_uniprot_sequence" in registry.registry
    assert "get_pdb_structure" in registry.registry
    assert "get_string_interactions" in registry.registry


def test_get_mcp_registry_is_a_singleton_across_calls():
    first = dependencies.get_mcp_registry()
    second = dependencies.get_mcp_registry()
    assert first is second


def test_get_mcp_registry_registers_skills_from_settings_skills_root(monkeypatch, tmp_path):
    skill_dir = tmp_path / "enrich"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: gene_enrichment\ndescription: test skill\n---\nBody\n",
        encoding="utf-8",
    )
    (skill_dir / "uv.lock").write_text("locked==1.0.0\n", encoding="utf-8")
    monkeypatch.setattr(dependencies.settings, "SKILLS_ROOT", str(tmp_path))

    registry = dependencies.get_mcp_registry()

    assert "gene_enrichment" in registry.registry
    # Bio tools stay registered alongside skills.
    assert "get_uniprot_sequence" in registry.registry


def test_get_mcp_registry_tolerates_missing_skills_root(monkeypatch, tmp_path):
    missing = tmp_path / "does_not_exist"
    monkeypatch.setattr(dependencies.settings, "SKILLS_ROOT", str(missing))

    registry = dependencies.get_mcp_registry()

    # No skills registered, but construction still succeeds and bio tools
    # are still present.
    assert "get_uniprot_sequence" in registry.registry


def test_get_mcp_registry_tolerates_register_skills_raising(monkeypatch):
    def _boom(registry, skills_root):
        raise RuntimeError("simulated skill compilation failure")

    monkeypatch.setattr(dependencies, "register_skills", _boom)

    registry = dependencies.get_mcp_registry()

    # Does not propagate; bio tools are still registered.
    assert isinstance(registry, MCPServerRegistry)
    assert "get_uniprot_sequence" in registry.registry
