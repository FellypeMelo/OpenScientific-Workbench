"""Unit tests for the SKILL.md loader/compiler (RF-009).

Pure filesystem + YAML + JSON-Schema logic, no infra: a temp skills/ tree is
built per test.
"""
import pytest

from src.infrastructure.mcp.server_registry import MCPServerRegistry
from src.infrastructure.skills.skill_compiler import compile_to_mcp_tool
from src.infrastructure.skills.skill_loader import (
    SkillParseError,
    discover_skills,
    load_skill,
)
from src.infrastructure.skills.skill_registration import register_skills

_SKILL_MD = """---
name: gene_enrichment
description: Runs gene set enrichment analysis
parameters:
  min_genes:
    type: integer
    default: 200
  organism:
    type: string
    default: human
  gene_list:
    type: array
---
# Gene Enrichment
Runs an enrichment analysis over the supplied gene list.
"""


def _write_skill(root, name: str, body: str = _SKILL_MD, with_lock: bool = True):
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")
    if with_lock:
        (skill_dir / "uv.lock").write_text("locked==1.0.0\n", encoding="utf-8")
    return skill_dir


def test_load_skill_parses_frontmatter(tmp_path):
    skill_dir = _write_skill(tmp_path, "enrich")

    skill = load_skill(str(skill_dir / "SKILL.md"))

    assert skill.name == "gene_enrichment"
    assert skill.description.startswith("Runs gene set enrichment")
    assert skill.parameters["min_genes"]["type"] == "integer"
    assert skill.parameters["min_genes"]["default"] == 200


def test_compile_to_mcp_tool_builds_json_schema(tmp_path):
    skill = load_skill(str(_write_skill(tmp_path, "enrich") / "SKILL.md"))

    tool = compile_to_mcp_tool(skill)

    assert tool["name"] == "gene_enrichment"
    schema = tool["inputSchema"]
    assert schema["type"] == "object"
    assert schema["properties"]["min_genes"]["type"] == "integer"
    assert schema["properties"]["min_genes"]["default"] == 200
    # A parameter without a default is required.
    assert "gene_list" in schema["required"]
    assert "min_genes" not in schema["required"]


def test_missing_closing_fence_raises_skill_parse_error(tmp_path):
    bad = "---\nname: broken\ndescription: no closing fence\n"
    skill_dir = tmp_path / "broken"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(bad, encoding="utf-8")

    with pytest.raises(SkillParseError):
        load_skill(str(skill_dir / "SKILL.md"))


def test_discover_skills_walks_root(tmp_path):
    _write_skill(tmp_path, "skill_a")
    _write_skill(tmp_path, "skill_b")

    skills = discover_skills(str(tmp_path))

    assert {s.name for s in skills} == {"gene_enrichment"}  # both share the same name field
    assert len(skills) == 2


def test_register_skills_makes_tool_routable(tmp_path):
    _write_skill(tmp_path, "enrich")
    registry = MCPServerRegistry()

    registered = register_skills(registry, str(tmp_path))

    assert "gene_enrichment" in registered
    assert "gene_enrichment" in registry.registry


@pytest.mark.asyncio
async def test_register_skills_skips_skill_without_lockfile(tmp_path):
    # A skill lacking environment.yaml/uv.lock must NOT compile/register
    # (reproducibility gate per docs/standards/skill_creation.md).
    _write_skill(tmp_path, "no_lock", with_lock=False)
    registry = MCPServerRegistry()

    registered = register_skills(registry, str(tmp_path))

    assert registered == []
    assert registry.registry == {}
