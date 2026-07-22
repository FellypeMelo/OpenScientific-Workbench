"""Sequence/structure/domain-database DB adapters calling real public REST
APIs (Fase 2 DB-adapter catalog, "structure" group -- see
``docs/tools/db_adapter_catalog.md``).

Same shape as ``src/infrastructure/mcp/bio_direct_adapters.py`` (RF-004): a
thin async wrapper class around an optionally-injected ``httpx.AsyncClient``,
one method per tool, a shared ``*APIError(RuntimeError)`` subclass raised on
a bad/unexpected response shape, and a module-level
``register_structure_db_tools(registry, client=None) -> List[str]``.

Six real, unauthenticated public APIs, callable directly with zero extra
infrastructure. Every endpoint/status-code below was verified live (not
guessed) before being encoded here:

- UniProt (``query_uniprot``): ``GET
  https://rest.uniprot.org/uniprotkb/search?query=...&format=json``. This is
  the *search* endpoint (query syntax, arbitrary result count) -- distinct
  from ``get_uniprot_sequence`` in ``bio_direct_adapters.py``, which already
  covers "give me one accession's canonical sequence" via the entry-by-
  accession endpoint. Response is ``{"results": [...]}``.
- AlphaFold DB (``query_alphafold``): ``GET
  https://alphafold.ebi.ac.uk/api/prediction/{qualifier}``. Returns a JSON
  *array* (even for a single UniProt accession, since some qualifiers span
  multiple model fragments) of prediction summary objects (``cifUrl``,
  ``pdbUrl``, ``paeImageUrl``, per-residue confidence stats, ...). A
  malformed identifier answers ``400``; a well-formed one with no prediction
  answers ``404`` -- both verified live and handled explicitly below.
- InterPro (``query_interpro``): ``GET
  https://www.ebi.ac.uk/interpro/api/entry/{source_database}/protein/uniprot/{accession}?format=json``
  (``source_database`` defaults to ``"interpro"``, the consolidated view;
  a member database like ``"pfam"`` can be passed instead). Response is
  ``{"count": N, "results": [...]}``. Verified live that a protein with zero
  matching entries answers a bare ``204 No Content`` (not a ``404``) --
  treated as a legitimate empty result, not an error.
- RCSB PDB search (``query_pdb``): ``POST
  https://search.rcsb.org/rcsbsearch/v2/query`` -- the real RCSB Search API
  (https://search.rcsb.org/#search-api), *searching* for entries, not
  downloading structure files (``get_pdb_structure`` in
  ``bio_direct_adapters.py`` already covers file download). Response is
  ``{"total_count": N, "result_set": [...]}``. Verified live that a query
  matching zero entries answers a bare ``204 No Content``.
- RCSB PDB batch identifiers (``query_pdb_identifiers``): ``GET
  https://data.rcsb.org/rest/v1/core/entry/{pdb_id}`` (the RCSB Data API)
  once per identifier, optionally also downloading each identifier's raw
  ``.pdb`` coordinate file (``https://files.rcsb.org/download/{pdb_id}.pdb``,
  same URL ``get_pdb_structure`` uses) when ``include_files=True``.
- EMDB (``query_emdb``): ``GET
  https://www.ebi.ac.uk/emdb/api/entry/{numeric_id}`` (the EMDB REST API;
  both a bare numeric id like ``"1832"`` and an ``"EMD-1832"``-style id are
  accepted as input and normalized to the numeric path segment the live API
  expects). Response is a large, faithfully-passed-through JSON object keyed
  by (among others) ``admin`` (title/authors/key dates) and
  ``structure_determination_list`` (method/resolution/microscopy) -- not
  re-shaped into a bespoke summary, since EMDB's own schema already varies
  by determination method (single particle vs. tomography vs. subtomogram
  averaging) and hand-picking a fixed subset of fields would silently drop
  data for methods this adapter wasn't tested against.

Structured-args-only limitation
--------------------------------
The original Biomni paper's version of these tools accepts a free-text
``query: str`` and relies on an LLM schema-parsing layer to turn it into the
right endpoint call; OSW has no such NL-to-query layer wired into this
adapter tier. Every tool below therefore requires the caller (an agent/DAG
node with a known accession/id/query-syntax string, not a human typing
prose) to pass already-structured arguments -- see each method's docstring
for its exact argument names. ``query_uniprot``'s and ``query_pdb``'s
``query`` arguments are each database's own native query syntax (UniProt
query syntax / an RCSB Search API query node respectively), not natural
language -- faking NL support here would mean either silently mis-parsing
free text into the wrong endpoint or quietly no-op'ing; neither is
acceptable, so it is not attempted.

No retry/backoff helper exists yet anywhere in this codebase's HTTP adapters
(a real, confirmed gap -- see ``docs/tools/db_adapter_catalog.md``); adding a
shared one is out of scope for this pass, matching the sibling DB-adapter
modules written alongside this one (``expression_browser_db_adapters.py``,
``proteomics_pharma_db_adapters.py``): a working adapter without retry beats
a half-finished one blocked on building that helper.
"""
import logging
from typing import Any, Dict, List, Optional, Union

import httpx

from src.infrastructure.mcp.server_registry import MCPServerRegistry

logger = logging.getLogger(__name__)

UNIPROT_SEARCH_URL = "https://rest.uniprot.org/uniprotkb/search"
ALPHAFOLD_PREDICTION_BASE_URL = "https://alphafold.ebi.ac.uk/api/prediction"
INTERPRO_BASE_URL = "https://www.ebi.ac.uk/interpro/api"
RCSB_SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
RCSB_DATA_ENTRY_BASE_URL = "https://data.rcsb.org/rest/v1/core/entry"
RCSB_FILES_BASE_URL = "https://files.rcsb.org/download"
EMDB_ENTRY_BASE_URL = "https://www.ebi.ac.uk/emdb/api/entry"

# Generous but bounded -- these are real, sometimes slow, third-party services.
DEFAULT_TIMEOUT_SECONDS = 30.0

#: MCP tool name -> what each method below implements.
STRUCTURE_DB_TOOL_NAMES = (
    "query_uniprot",
    "query_alphafold",
    "query_interpro",
    "query_pdb",
    "query_pdb_identifiers",
    "query_emdb",
)


class StructureAPIError(RuntimeError):
    """Raised when a real structure/sequence-database REST API call fails: a
    non-2xx response (other than a clean 404, or the ``204 No Content``
    "no results" responses InterPro/RCSB Search document, both reported as a
    more specific message) or a response body that doesn't have the shape
    this adapter expects."""


class StructureDBAdapters:
    """Thin async wrapper around the real UniProt/AlphaFold/InterPro/RCSB/EMDB
    REST APIs.

    An `httpx.AsyncClient` can be injected (tests use `httpx.MockTransport`,
    mirroring `BioDirectAdapters`'s test pattern); otherwise a fresh client
    is created per call, so callers never have to manage a client lifecycle.
    """

    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._client = client

    async def _get(self, url: str, *, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
        if self._client is not None:
            return await self._client.get(url, params=params)
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            return await client.get(url, params=params)

    async def _post(self, url: str, *, json_body: Dict[str, Any]) -> httpx.Response:
        if self._client is not None:
            return await self._client.post(url, json=json_body)
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            return await client.post(url, json=json_body)

    # --- query_uniprot -------------------------------------------------

    async def query_uniprot(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Searches the real UniProtKB REST API (structured args only -- see
        module docstring).

        Required: ``query`` (str) -- UniProt's own query syntax, e.g.
        ``'gene:BRCA1 AND organism_id:9606'`` or ``'insulin'`` (a plain
        keyword is also valid UniProt query syntax). For "give me this one
        accession's sequence" use ``get_uniprot_sequence`` instead.
        Optional: ``fields`` (str, comma-separated UniProt return fields),
        ``size`` (int, default 25, capped results per UniProt's own limits).
        """
        args = arguments or {}
        query = args.get("query")
        if not query or not str(query).strip():
            raise ValueError(
                "query_uniprot requires a non-empty 'query' argument using UniProt's own "
                "query syntax (e.g. 'gene:BRCA1 AND organism_id:9606'), not a natural-language "
                "question -- this adapter has no NL-to-query layer. Use get_uniprot_sequence "
                "instead for a single accession's sequence."
            )
        query = str(query).strip()
        size = int(args.get("size") or 25)

        params: Dict[str, Any] = {"query": query, "format": "json", "size": size}
        fields = args.get("fields")
        if fields and str(fields).strip():
            params["fields"] = str(fields).strip()

        response = await self._get(UNIPROT_SEARCH_URL, params=params)
        response.raise_for_status()

        try:
            data = response.json()
            results = data["results"]
            if not isinstance(results, list):
                raise TypeError("'results' was not a list")
        except (ValueError, KeyError, TypeError) as exc:
            raise StructureAPIError(
                f"UniProt search response for query '{query}' did not contain the expected "
                "'results' list."
            ) from exc

        return {"query": query, "count": len(results), "results": results}

    # --- query_alphafold -------------------------------------------------

    async def query_alphafold(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Fetches structure-prediction metadata from the real AlphaFold DB API.

        Required: ``qualifier`` (str) -- a UniProt accession (e.g.
        ``'P69905'``) or AlphaFold DB entry id.
        """
        args = arguments or {}
        qualifier = args.get("qualifier") or args.get("accession")
        if not qualifier or not str(qualifier).strip():
            raise ValueError(
                "query_alphafold requires a non-empty 'qualifier' argument -- a UniProt "
                "accession (e.g. 'P69905') or AlphaFold DB entry id."
            )
        qualifier = str(qualifier).strip()

        url = f"{ALPHAFOLD_PREDICTION_BASE_URL}/{qualifier}"
        response = await self._get(url)
        if response.status_code == 404:
            raise StructureAPIError(f"No AlphaFold DB prediction was found for '{qualifier}'.")
        if response.status_code == 400:
            raise StructureAPIError(
                f"AlphaFold DB rejected '{qualifier}' as an invalid identifier."
            )
        response.raise_for_status()

        try:
            data = response.json()
            if not isinstance(data, list):
                raise TypeError("response body was not a list")
        except (ValueError, TypeError) as exc:
            raise StructureAPIError(
                "AlphaFold DB returned an unexpected response shape (expected a list)."
            ) from exc
        if not data:
            raise StructureAPIError(f"AlphaFold DB returned no predictions for '{qualifier}'.")

        return {"qualifier": qualifier, "count": len(data), "predictions": data}

    # --- query_interpro -------------------------------------------------

    async def query_interpro(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Fetches InterPro domain/family entries for a protein from the real
        InterPro REST API.

        Required: ``accession`` (str) -- a UniProt protein accession (e.g.
        ``'P69905'``).
        Optional: ``source_database`` (str, default ``'interpro'`` -- the
        consolidated view; a member database name like ``'pfam'`` narrows to
        just that database's own entries).
        """
        args = arguments or {}
        accession = args.get("accession")
        if not accession or not str(accession).strip():
            raise ValueError(
                "query_interpro requires a non-empty 'accession' argument -- a UniProt "
                "protein accession (e.g. 'P69905')."
            )
        accession = str(accession).strip()
        source_database = str(args.get("source_database") or "interpro").strip() or "interpro"

        url = f"{INTERPRO_BASE_URL}/entry/{source_database}/protein/uniprot/{accession}"
        response = await self._get(url, params={"format": "json"})
        # InterPro's real API answers "no domain/family entries matched" with
        # a bare 204 (not a 404) -- confirmed live. A legitimate empty
        # result, not an error.
        if response.status_code == 204:
            return {"accession": accession, "source_database": source_database, "count": 0, "results": []}
        if response.status_code == 404:
            raise StructureAPIError(
                f"InterPro found no '{source_database}' entry data for '{accession}'."
            )
        response.raise_for_status()

        try:
            data = response.json()
            results = data["results"]
            if not isinstance(results, list):
                raise TypeError("'results' was not a list")
        except (ValueError, KeyError, TypeError) as exc:
            raise StructureAPIError(
                f"InterPro response for '{accession}' did not contain the expected 'results' list."
            ) from exc

        return {
            "accession": accession,
            "source_database": source_database,
            "count": data.get("count", len(results)),
            "results": results,
        }

    # --- query_pdb ---------------------------------------------------------

    async def query_pdb(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Searches the real RCSB PDB Search API (structured args only -- see
        module docstring). Searches for entries; does not download structure
        files (use ``get_pdb_structure`` for that).

        Required: ``query`` -- either a plain string (used verbatim as an
        RCSB full-text search term) or a dict containing an already-
        structured RCSB Search API query node
        (https://search.rcsb.org/#search-api), passed straight through as
        the request's ``"query"`` field for callers who need RCSB's richer
        attribute/sequence/structure search services.
        Optional: ``return_type`` (str, default ``'entry'``), ``rows`` (int,
        default 10), ``start`` (int, default 0) -- pagination.
        """
        args = arguments or {}
        query = args.get("query")
        if isinstance(query, str):
            query = query.strip()
            if not query:
                raise ValueError(
                    "query_pdb requires a non-empty 'query' argument: either a plain string "
                    "(an RCSB full-text search term) or a dict containing a direct, "
                    "already-structured RCSB Search API query node -- this adapter has no "
                    "natural-language-to-query layer."
                )
            query_node: Dict[str, Any] = {
                "type": "terminal",
                "service": "full_text",
                "parameters": {"value": query},
            }
        elif isinstance(query, dict) and query:
            query_node = query
        else:
            raise ValueError(
                "query_pdb requires a non-empty 'query' argument: either a plain string "
                "(an RCSB full-text search term) or a dict containing a direct, "
                "already-structured RCSB Search API query node -- this adapter has no "
                "natural-language-to-query layer."
            )

        return_type = str(args.get("return_type") or "entry")
        rows = int(args.get("rows") or 10)
        start = int(args.get("start") or 0)
        body = {
            "query": query_node,
            "return_type": return_type,
            "request_options": {"paginate": {"start": start, "rows": rows}},
        }

        response = await self._post(RCSB_SEARCH_URL, json_body=body)
        # A query matching zero entries gets a bare 204 (confirmed live),
        # not a 200 with an empty result_set.
        if response.status_code == 204:
            return {"total_count": 0, "result_set": []}
        response.raise_for_status()

        try:
            data = response.json()
            result_set = data["result_set"]
            if not isinstance(result_set, list):
                raise TypeError("'result_set' was not a list")
        except (ValueError, KeyError, TypeError) as exc:
            raise StructureAPIError(
                "RCSB PDB search response did not contain the expected 'result_set' list."
            ) from exc

        return {"total_count": data.get("total_count", len(result_set)), "result_set": result_set}

    # --- query_pdb_identifiers ----------------------------------------------

    async def query_pdb_identifiers(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Retrieves detailed entry data (and, optionally, raw structure
        files) for a batch of PDB identifiers from the real RCSB Data API.

        Required: ``identifiers`` -- a PDB id, or a list of them (e.g.
        ``['1CRN', '4HHB']``).
        Optional: ``include_files`` (bool, default ``False``) -- also
        downloads each identifier's raw ``.pdb`` coordinate file (same
        source ``get_pdb_structure`` uses).

        Each identifier is fetched in turn; the first identifier that fails
        (not found, or any other non-2xx response) raises immediately and
        aborts the batch, matching this adapter's single-identifier tools'
        error handling rather than silently returning a partial result set.
        """
        args = arguments or {}
        raw_identifiers: Optional[Union[str, List[str]]] = args.get("identifiers")
        identifiers: List[str] = (
            [raw_identifiers] if isinstance(raw_identifiers, str) else list(raw_identifiers or [])
        )
        identifiers = [str(i).strip().upper() for i in identifiers if str(i).strip()]
        if not identifiers:
            raise ValueError(
                "query_pdb_identifiers requires a non-empty 'identifiers' argument (a PDB id, "
                "or a list of them, e.g. ['1CRN', '4HHB'])."
            )
        include_files = bool(args.get("include_files", False))

        entries = []
        for pdb_id in identifiers:
            entries.append(await self._fetch_one_pdb_identifier(pdb_id, include_files))
        return {"count": len(entries), "entries": entries}

    async def _fetch_one_pdb_identifier(self, pdb_id: str, include_files: bool) -> Dict[str, Any]:
        response = await self._get(f"{RCSB_DATA_ENTRY_BASE_URL}/{pdb_id}")
        if response.status_code == 404:
            raise StructureAPIError(f"PDB entry '{pdb_id}' was not found in the RCSB Data API.")
        response.raise_for_status()

        try:
            data = response.json()
            if not isinstance(data, dict):
                raise TypeError("response body was not an object")
        except (ValueError, TypeError) as exc:
            raise StructureAPIError(
                f"RCSB Data API response for '{pdb_id}' did not contain the expected entry data."
            ) from exc

        entry: Dict[str, Any] = {"pdb_id": pdb_id, "data": data}
        if include_files:
            file_response = await self._get(f"{RCSB_FILES_BASE_URL}/{pdb_id}.pdb")
            if file_response.status_code == 404:
                raise StructureAPIError(f"PDB entry '{pdb_id}' has no downloadable structure file.")
            file_response.raise_for_status()
            entry["structure"] = file_response.text
        return entry

    # --- query_emdb -------------------------------------------------------

    async def query_emdb(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Fetches entry metadata from the real Electron Microscopy Data Bank
        (EMDB) REST API.

        Required: ``emdb_id`` (str) -- e.g. ``'EMD-1832'`` or bare ``'1832'``
        (both accepted; normalized to the numeric id the live API expects).
        """
        args = arguments or {}
        emdb_id = args.get("emdb_id") or args.get("id")
        if not emdb_id or not str(emdb_id).strip():
            raise ValueError(
                "query_emdb requires a non-empty 'emdb_id' argument (e.g. 'EMD-1832' or '1832')."
            )
        raw_id = str(emdb_id).strip().upper()
        numeric_id = raw_id[4:] if raw_id.startswith("EMD-") else raw_id
        display_id = f"EMD-{numeric_id}"

        response = await self._get(f"{EMDB_ENTRY_BASE_URL}/{numeric_id}")
        if response.status_code == 404:
            raise StructureAPIError(f"EMDB entry '{display_id}' was not found.")
        response.raise_for_status()

        try:
            data = response.json()
            if not isinstance(data, dict) or "admin" not in data:
                raise TypeError("response body did not contain an 'admin' section")
        except (ValueError, TypeError) as exc:
            raise StructureAPIError(
                f"EMDB response for '{display_id}' did not contain the expected entry data."
            ) from exc

        return {"emdb_id": display_id, "data": data}


def register_structure_db_tools(
    registry: MCPServerRegistry, client: Optional[httpx.AsyncClient] = None
) -> List[str]:
    """Registers the structure/sequence-database DB tool handlers into
    `registry`.

    Returns the registered tool names. Always safe to call -- these APIs need
    no configuration/auth, so (unlike e.g. `register_skills`) there is no
    failure mode here worth guarding against at the call site.
    """
    adapters = StructureDBAdapters(client)
    handlers = {
        "query_uniprot": adapters.query_uniprot,
        "query_alphafold": adapters.query_alphafold,
        "query_interpro": adapters.query_interpro,
        "query_pdb": adapters.query_pdb,
        "query_pdb_identifiers": adapters.query_pdb_identifiers,
        "query_emdb": adapters.query_emdb,
    }
    for tool_name, handler in handlers.items():
        registry.register_server(tool_name, handler)
    return list(handlers.keys())
