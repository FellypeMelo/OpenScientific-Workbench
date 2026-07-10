"""SKILL.md loader (RF-009).

Discovers scientific Skills on disk and parses their mandatory YAML frontmatter
(see docs/standards/skill_creation.md) into a typed ``SkillDefinition``. The
compiler turns that into an MCP tool JSON-Schema so the orchestrator can route
to it.
"""
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml
from pydantic import BaseModel, Field


class SkillParseError(ValueError):
    """Raised when a SKILL.md file is missing or has malformed frontmatter."""


class SkillDefinition(BaseModel):
    name: str
    description: str = ""
    parameters: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    body: str = ""


def split_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Split leading ``---`` fenced YAML frontmatter from the markdown body."""
    stripped = text.lstrip("﻿")  # tolerate a UTF-8 BOM
    lines = stripped.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillParseError("SKILL.md must begin with a YAML frontmatter fence '---'.")

    closing = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if closing is None:
        raise SkillParseError("SKILL.md frontmatter is missing its closing '---' fence.")

    try:
        data = yaml.safe_load("\n".join(lines[1:closing])) or {}
    except yaml.YAMLError as exc:
        raise SkillParseError(f"Invalid YAML frontmatter: {exc}") from exc

    if not isinstance(data, dict):
        raise SkillParseError("SKILL.md frontmatter must be a YAML mapping.")

    return data, "\n".join(lines[closing + 1 :])


def load_skill(skill_md_path: str) -> SkillDefinition:
    """Parse a single SKILL.md file into a SkillDefinition."""
    data, body = split_frontmatter(Path(skill_md_path).read_text(encoding="utf-8"))
    if "name" not in data:
        raise SkillParseError("SKILL.md frontmatter must define 'name'.")

    return SkillDefinition(
        name=str(data["name"]),
        description=str(data.get("description", "")),
        parameters=data.get("parameters") or {},
        body=body,
    )


def discover_skills(skills_root: str) -> List[SkillDefinition]:
    """Load every ``<skills_root>/*/SKILL.md`` into a SkillDefinition (sorted)."""
    return [load_skill(str(p)) for p in sorted(Path(skills_root).glob("*/SKILL.md"))]
