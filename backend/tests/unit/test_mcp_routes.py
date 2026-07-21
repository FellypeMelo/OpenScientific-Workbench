"""Unit tests for `POST /api/v1/mcp/tools/call` (`presentation/routes/mcp.py`,
RF-004/RF-009 wiring).

The `MCPRouterPort` is faked via `app.dependency_overrides` (same pattern
`test_hpc_routes.py` uses for `HPCJobDispatcherPort`) -- these tests are about
the route/wiring/error-mapping layer, not re-testing `MCPServerRegistry` or
the direct bio adapters themselves (covered by `test_mcp_jsonrpc_client.py`,
`test_bio_direct_adapters.py`, and `test_mcp_registry_dependency.py`).
"""
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from src.domain.ports.mcp_router import MCPRouterPort
from src.infrastructure.mcp.bio_direct_adapters import BioAPIError
from src.infrastructure.mcp.server_registry import MCPServerRegistry
from src.presentation.dependencies import get_mcp_registry
from src.presentation.main import app
from src.presentation.middleware.jwt_auth import create_access_token

client = TestClient(app)


class _FakeRouter(MCPRouterPort):
    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc
        self.calls = []

    async def route(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        if self._exc is not None:
            raise self._exc
        return self._result


@pytest.fixture
def _override_registry():
    def _apply(fake_router):
        app.dependency_overrides[get_mcp_registry] = lambda: fake_router

    yield _apply
    app.dependency_overrides.pop(get_mcp_registry, None)


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {create_access_token(uuid4(), iam_role='scientist')}"}


def test_call_mcp_tool_requires_auth(_override_registry):
    _override_registry(_FakeRouter(result="ignored"))

    response = client.post(
        "/api/v1/mcp/tools/call",
        json={"tool_name": "get_uniprot_sequence", "arguments": {"accession": "P69905"}},
    )

    assert response.status_code == 401


def test_call_mcp_tool_success_routes_through_the_registry(_override_registry):
    fake = _FakeRouter(result="OK:get_uniprot_sequence")
    _override_registry(fake)

    response = client.post(
        "/api/v1/mcp/tools/call",
        json={"tool_name": "get_uniprot_sequence", "arguments": {"accession": "P69905"}},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {"result": "OK:get_uniprot_sequence"}
    assert fake.calls == [("get_uniprot_sequence", {"accession": "P69905"})]


def test_call_mcp_tool_defaults_arguments_to_empty_dict(_override_registry):
    fake = _FakeRouter(result="OK")
    _override_registry(fake)

    response = client.post(
        "/api/v1/mcp/tools/call",
        json={"tool_name": "get_uniprot_sequence"},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert fake.calls == [("get_uniprot_sequence", {})]


def test_call_mcp_tool_empty_tool_name_returns_400(_override_registry):
    fake = _FakeRouter(result="unreachable")
    _override_registry(fake)

    response = client.post(
        "/api/v1/mcp/tools/call",
        json={"tool_name": "", "arguments": {}},
        headers=_auth_headers(),
    )

    assert response.status_code == 400
    assert "Tool name cannot be empty" in response.json()["detail"]
    assert fake.calls == []  # RouteMCPToolUseCase validates before ever calling the router.


def test_call_mcp_tool_bio_api_error_returns_502(_override_registry):
    _override_registry(_FakeRouter(exc=BioAPIError("UniProt accession 'BOGUS' was not found.")))

    response = client.post(
        "/api/v1/mcp/tools/call",
        json={"tool_name": "get_uniprot_sequence", "arguments": {"accession": "BOGUS"}},
        headers=_auth_headers(),
    )

    assert response.status_code == 502
    assert "not found" in response.json()["detail"]


def test_call_mcp_tool_upstream_httpx_error_returns_502(_override_registry):
    _override_registry(_FakeRouter(exc=httpx.ConnectError("connection refused")))

    response = client.post(
        "/api/v1/mcp/tools/call",
        json={"tool_name": "get_string_interactions", "arguments": {"identifiers": ["TP53"]}},
        headers=_auth_headers(),
    )

    assert response.status_code == 502


def test_call_mcp_tool_unregistered_tool_returns_registry_fallback_message(_override_registry):
    # A real (empty) registry, not a fake -- exercises the actual "not
    # registered" fallback string from `MCPServerRegistry.route`, still
    # surfaced as a clean 200 (it's a real, non-exceptional response from the
    # router), matching `RouteMCPToolUseCase.execute`'s contract.
    _override_registry(MCPServerRegistry())

    response = client.post(
        "/api/v1/mcp/tools/call",
        json={"tool_name": "totally_unregistered_tool", "arguments": {}},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert "not registered" in response.json()["result"]
