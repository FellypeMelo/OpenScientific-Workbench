"""Compiles a SkillDefinition into an MCP tool JSON-Schema (RF-009).

This is the ``skill-to-mcp`` step: the frontmatter's ``parameters`` become a
strict JSON-Schema ``inputSchema`` (typed, with defaults and a required list),
which is exactly what an MCP client/LLM needs to call the tool safely.
"""
from typing import Any, Dict

from src.infrastructure.skills.skill_loader import SkillDefinition

_JSON_SCHEMA_TYPES = {"integer", "string", "number", "boolean", "array", "object"}


def compile_to_mcp_tool(skill: SkillDefinition) -> Dict[str, Any]:
    properties: Dict[str, Any] = {}
    required = []

    for param_name, spec in skill.parameters.items():
        spec = spec or {}
        param_type = spec.get("type", "string")
        if param_type not in _JSON_SCHEMA_TYPES:
            param_type = "string"

        prop: Dict[str, Any] = {"type": param_type}
        if "default" in spec:
            prop["default"] = spec["default"]
        else:
            # A parameter with no default is mandatory.
            required.append(param_name)
        if "description" in spec:
            prop["description"] = str(spec["description"])

        properties[param_name] = prop

    input_schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        input_schema["required"] = required

    return {
        "name": skill.name,
        "description": skill.description,
        "inputSchema": input_schema,
    }
