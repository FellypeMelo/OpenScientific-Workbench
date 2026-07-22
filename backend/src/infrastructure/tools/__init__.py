"""Sandboxed "action tool" MCP handlers (Biomni-style, see
`backend/docs/tools/action_tool_catalog.md`).

Each sibling module (`cloning.py`, `genomics.py`, ...) registers one category
of tools via `register_<category>_tools(registry, driver) -> List[str]`,
following the exact convention `infrastructure/mcp/bio_direct_adapters.py`
established for the (network-only, unsandboxed) bio/DB adapters. Every
handler here instead runs inside the bwrap sandbox via `run_in_sandbox`
(`_sandbox_tool_base.py`) -- see that module's docstring for why, and
`presentation/dependencies.py::get_mcp_registry` for where these get wired
into the process-wide registry.
"""
