"""MCP tool-call routing route (RF-004/RF-009 wiring).

`POST /api/v1/mcp/tools/call` routes a semantic `{tool_name, arguments}` call
through `RouteMCPToolUseCase` against the shared `MCPServerRegistry` singleton
(`presentation/dependencies.py::get_mcp_registry`), which by default has the
real direct bio-tool adapters (RF-004: UniProt/RCSB PDB/STRING) registered,
plus any reproducible compiled Skills (RF-009) discovered under
`settings.SKILLS_ROOT`.

Protected by the global JWT middleware like every other route (no entry in
`JWTAuthMiddleware.UNAUTHENTICATED_PATHS`); this route has no per-user owned
resource to check (unlike `sessions`/`workspaces`/`hpc`), so -- mirroring
`routes/manuscript.py` -- it does not additionally depend on
`get_current_user_id`.
"""
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.application.use_cases.route_mcp_tool import RouteMCPToolUseCase
from src.domain.ports.mcp_router import MCPRouterPort
from src.infrastructure.mcp.bio_direct_adapters import BioAPIError
from src.presentation.dependencies import get_mcp_registry

router = APIRouter(prefix="/mcp", tags=["mcp"])


class MCPToolCallRequest(BaseModel):
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class MCPToolCallResponse(BaseModel):
    result: str


@router.post("/tools/call", response_model=MCPToolCallResponse)
async def call_mcp_tool(
    request: MCPToolCallRequest,
    registry: MCPRouterPort = Depends(get_mcp_registry),
) -> MCPToolCallResponse:
    use_case = RouteMCPToolUseCase(router=registry)
    try:
        result = await use_case.execute(tool_name=request.tool_name, arguments=request.arguments)
    except ValueError as exc:
        # Mirrors the convention used across this codebase (e.g.
        # `routes/hpc.py`, `routes/workspaces.py`): a domain-level `ValueError`
        # -- here, an empty/missing `tool_name`, or a direct bio adapter
        # rejecting malformed `arguments` (see `bio_direct_adapters.py`) --
        # maps to 400, the request itself is invalid.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (BioAPIError, httpx.HTTPError) as exc:
        # The upstream public bio API (UniProt/RCSB PDB/STRING) itself failed
        # or returned something this adapter couldn't parse -- a genuine
        # dependency failure, not a malformed request from this caller, so
        # 502 (Bad Gateway) rather than 400/500.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return MCPToolCallResponse(result=result)
