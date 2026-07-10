"""Registers compiled Skills into the MCP registry so they become routable (RF-009).

Applies the reproducibility gate from docs/standards/skill_creation.md: a Skill
directory without a dependency lockfile (``uv.lock`` / ``environment.yaml``) is
skipped -- it cannot be trusted to run reproducibly, so it is never compiled or
registered.
"""
from pathlib import Path
from typing import Any, Dict, List

from src.infrastructure.mcp.server_registry import MCPServerRegistry
from src.infrastructure.skills.skill_compiler import compile_to_mcp_tool
from src.infrastructure.skills.skill_loader import load_skill

_LOCKFILES = ("uv.lock", "environment.yaml")


def _make_handler(tool: Dict[str, Any]):
    """A routable handler for a compiled skill.

    Real execution happens in the gVisor sandbox (RF-005, infra-blocked here), so
    this returns an explicit "compiled/routable but not yet executed" message
    rather than faking a successful run.
    """

    def handler(arguments: Dict[str, Any]) -> str:
        return (
            f"Skill '{tool['name']}' is registered and schema-compiled; sandbox "
            f"execution is pending (RF-005). Received args: {sorted(arguments or {})}"
        )

    return handler


def register_skills(registry: MCPServerRegistry, skills_root: str) -> List[str]:
    """Discover, compile and register every reproducible Skill under ``skills_root``.

    Returns the list of registered tool names (skills failing the lockfile gate
    are silently skipped and excluded from the result)."""
    registered: List[str] = []
    for skill_md in sorted(Path(skills_root).glob("*/SKILL.md")):
        if not any((skill_md.parent / lock).exists() for lock in _LOCKFILES):
            continue
        tool = compile_to_mcp_tool(load_skill(str(skill_md)))
        registry.register_server(tool["name"], _make_handler(tool))
        registered.append(tool["name"])
    return registered
