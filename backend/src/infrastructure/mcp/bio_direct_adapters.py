"""Direct bio-tool adapters calling the real public UniProt/RCSB PDB/STRING REST
APIs (RF-004).

These three public bioinformatics APIs are free and unauthenticated, and are
callable directly today with zero extra infrastructure -- no MCP gateway/
JSON-RPC hop is needed to reach them:

- UniProt (``get_uniprot_sequence``): ``GET
  https://rest.uniprot.org/uniprotkb/{accession}.json``
- RCSB PDB (``get_pdb_structure``): ``GET
  https://files.rcsb.org/download/{pdb_id}.pdb`` (returns the raw PDB-format
  structure file -- atomic coordinates -- rather than just entry metadata).
- STRING (``get_string_interactions``): ``GET
  https://string-db.org/api/json/network?identifiers=...&species=...``

This module is the DEFAULT bio-tool path (see
``presentation/dependencies.py::get_mcp_registry``). The generic
MCP-gateway path (``infrastructure/mcp/jsonrpc_client.py`` +
``infrastructure/mcp/bio_adapters.py``) is kept alongside it, dormant and
unregistered by default, as an optional alternative for anyone who does have a
real MCP-compatible gateway server to point at later -- it is not deleted.
"""
import logging
from typing import Any, Dict, List, Optional, Union

import httpx

from src.infrastructure.mcp.server_registry import MCPServerRegistry

logger = logging.getLogger(__name__)

UNIPROT_BASE_URL = "https://rest.uniprot.org/uniprotkb"
RCSB_FILES_BASE_URL = "https://files.rcsb.org/download"
STRING_BASE_URL = "https://string-db.org/api/json/network"

# Generous but bounded -- these are real, sometimes slow, third-party services.
DEFAULT_TIMEOUT_SECONDS = 30.0

#: MCP tool name -> the (unchanged from `bio_adapters.py`) name every caller
#: already routes through. Kept identical intentionally: this module is a
#: drop-in default for those same three tool names, not a new API surface.
DIRECT_BIO_TOOL_NAMES = (
    "get_uniprot_sequence",
    "get_pdb_structure",
    "get_string_interactions",
)


class BioAPIError(RuntimeError):
    """Raised when a direct bio REST API call fails: a non-2xx response (other
    than a clean 404, which is reported as a more specific `not found`
    message) or a response body that doesn't have the shape this adapter
    expects."""


class BioDirectAdapters:
    """Thin async wrapper around the three real public bio REST APIs.

    An `httpx.AsyncClient` can be injected (tests use `httpx.MockTransport`,
    mirroring `JSONRPCMCPClient`'s test pattern in
    `test_mcp_jsonrpc_client.py`); otherwise a fresh client is created per
    call, so callers never have to manage a client lifecycle.
    """

    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._client = client

    async def _get(self, url: str, *, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
        if self._client is not None:
            return await self._client.get(url, params=params)
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            return await client.get(url, params=params)

    async def get_uniprot_sequence(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Fetches a protein's canonical sequence from the real UniProtKB REST API."""
        accession = (arguments or {}).get("accession")
        if not accession or not str(accession).strip():
            raise ValueError(
                "get_uniprot_sequence requires a non-empty 'accession' argument "
                "(e.g. 'P69905')."
            )
        accession = str(accession).strip()

        url = f"{UNIPROT_BASE_URL}/{accession}.json"
        response = await self._get(url)
        if response.status_code == 404:
            raise BioAPIError(f"UniProt accession '{accession}' was not found.")
        response.raise_for_status()

        try:
            data = response.json()
            sequence = data["sequence"]["value"]
            length = data["sequence"]["length"]
        except (ValueError, KeyError, TypeError) as exc:
            raise BioAPIError(
                f"UniProt response for accession '{accession}' did not contain the "
                "expected sequence data."
            ) from exc

        return {"accession": accession, "sequence": sequence, "length": length}

    async def get_pdb_structure(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Fetches a structure's raw PDB-format coordinate file from RCSB PDB."""
        pdb_id = (arguments or {}).get("pdb_id")
        if not pdb_id or not str(pdb_id).strip():
            raise ValueError(
                "get_pdb_structure requires a non-empty 'pdb_id' argument (e.g. '1CRN')."
            )
        pdb_id = str(pdb_id).strip().upper()

        url = f"{RCSB_FILES_BASE_URL}/{pdb_id}.pdb"
        response = await self._get(url)
        if response.status_code == 404:
            raise BioAPIError(f"PDB entry '{pdb_id}' was not found.")
        response.raise_for_status()

        content = response.text
        if not content.strip():
            raise BioAPIError(f"RCSB PDB returned an empty structure file for '{pdb_id}'.")

        return {"pdb_id": pdb_id, "format": "pdb", "content": content}

    async def get_string_interactions(
        self, arguments: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Fetches a protein-protein interaction network from the real STRING API."""
        raw_identifiers: Optional[Union[str, List[str]]] = (arguments or {}).get("identifiers")
        identifiers: List[str] = (
            [raw_identifiers] if isinstance(raw_identifiers, str) else list(raw_identifiers or [])
        )
        identifiers = [str(i).strip() for i in identifiers if str(i).strip()]
        if not identifiers:
            raise ValueError(
                "get_string_interactions requires a non-empty 'identifiers' argument "
                "(a gene/protein identifier, or a list of them)."
            )
        species = (arguments or {}).get("species", 9606)  # Human by default.

        # STRING's documented multi-identifier separator is a percent-encoded
        # carriage return (`%0d`/`%0D`, RFC 3986 percent-encoding is
        # case-insensitive) between identifiers in the query string. Joining
        # on a literal `\r` and letting httpx's own query-string encoder
        # percent-escape it (rather than splicing a literal `"%0d"` into the
        # value, which httpx would then re-escape as `%250d`) produces exactly
        # that byte on the wire.
        params = {"identifiers": "\r".join(identifiers), "species": species}
        response = await self._get(STRING_BASE_URL, params=params)
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as exc:
            raise BioAPIError("STRING API returned a non-JSON response.") from exc
        if not isinstance(data, list):
            raise BioAPIError("STRING API returned an unexpected response shape (expected a list).")

        return data


def register_direct_bio_tools(
    registry: MCPServerRegistry, client: Optional[httpx.AsyncClient] = None
) -> List[str]:
    """Registers the direct (non-gateway) bio tool handlers into `registry`.

    Returns the registered tool names. Always safe to call -- these APIs need
    no configuration/auth, so (unlike e.g. `register_skills`) there is no
    failure mode here worth guarding against at the call site.
    """
    adapters = BioDirectAdapters(client)
    handlers = {
        "get_uniprot_sequence": adapters.get_uniprot_sequence,
        "get_pdb_structure": adapters.get_pdb_structure,
        "get_string_interactions": adapters.get_string_interactions,
    }
    for tool_name, handler in handlers.items():
        registry.register_server(tool_name, handler)
    return list(handlers.keys())
