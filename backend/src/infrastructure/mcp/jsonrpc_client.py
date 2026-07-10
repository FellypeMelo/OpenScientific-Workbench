"""JSON-RPC 2.0 transport client for remote MCP/bio tool servers (RF-004).

Speaks real JSON-RPC 2.0 over HTTP (httpx): builds the request envelope, sends
it, and unwraps ``result`` (raising on a JSON-RPC ``error``). An httpx client can
be injected for testing against a mock transport; otherwise one is created per
call. Real BioContextAI/MCPmed servers + JWT auth remain infra-blocked, but the
transport and bio tool mappings are real and unit-testable.
"""
import itertools
from typing import Any, Dict, Optional

import httpx


class JSONRPCError(RuntimeError):
    """Raised when a JSON-RPC response carries an ``error`` member."""


class JSONRPCMCPClient:
    def __init__(self, base_url: str, client: Optional[httpx.AsyncClient] = None):
        self.base_url = base_url
        self._client = client
        self._id_counter = itertools.count(1)

    async def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": next(self._id_counter),
        }

        if self._client is not None:
            response = await self._client.post(self.base_url, json=payload)
        else:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.base_url, json=payload)

        response.raise_for_status()
        data = response.json()
        if data.get("error") is not None:
            raise JSONRPCError(f"JSON-RPC error from '{method}': {data['error']}")
        return data.get("result")
