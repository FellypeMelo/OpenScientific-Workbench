"""Proteomics / pharmacology DB adapters calling real public REST APIs
(Fase 2 DB-adapter catalog, ``proteomics_pharma`` group).

Same shape as ``src/infrastructure/mcp/bio_direct_adapters.py`` (RF-004):
a thin async wrapper class around an optionally-injected ``httpx.AsyncClient``,
one method per tool, a shared ``*APIError(RuntimeError)`` subclass raised on a
bad/unexpected response shape, and a module-level
``register_proteomics_pharma_db_tools(registry, client=None) -> List[str]``.

Three real, unauthenticated public APIs, callable directly with zero extra
infrastructure:

- PRIDE Archive (``query_pride``): EBI's PRoteomics IDEntifications database.
  ``GET https://www.ebi.ac.uk/pride/ws/archive/v2/projects/{accession}`` for a
  direct project lookup, or
  ``GET https://www.ebi.ac.uk/pride/ws/archive/v2/search/projects?keyword=...``
  for a keyword search. Response shapes verified live against the real API
  (2024/2025 v2 schema): a project lookup returns a single JSON object keyed
  by (among others) ``accession``/``title``/``projectDescription``; a keyword
  search returns a plain JSON array of the same per-project object shape.
- Guide to PHARMACOLOGY / GtoPdb (``query_gtopdb``): IUPHAR/BPS pharmacology
  database. ``GET https://www.guidetopharmacology.org/services/{targets|ligands}/{id}``
  for a direct ID lookup (returns a single JSON object, e.g.
  ``{"targetId": 1797, "name": "epidermal growth factor receptor", ...}``), or
  ``GET https://www.guidetopharmacology.org/services/{targets|ligands}?name=...``
  for a name search (returns a JSON array of the same object shape). GtoPdb
  documents ``204 No Content`` for "no results" and ``404`` for an invalid
  identifier -- both verified live and both handled explicitly below.
- NCBI BLAST (``blast_sequence``): the real BLAST Common URL API
  (https://blast.ncbi.nlm.nih.gov/doc/blast-help/urlapi.html), the same
  two-step submit-then-poll protocol Biopython's ``NCBIWWW.qblast`` wraps --
  there is no synchronous "give me hits now" BLAST endpoint, so a working
  adapter for this tool *is* the submit/poll/fetch state machine, not an
  optional add-on:
    1. ``CMD=Put`` (POST -- a FASTA/raw sequence can exceed a GET URL's
       practical length, so unlike the other two tools here this step uses a
       real POST, not the shared ``_get`` helper) submits the search and
       returns an HTML page with an embedded Request ID (``RID``).
    2. ``CMD=Get&FORMAT_OBJECT=SearchInfo&RID=...`` is polled (bounded by
       ``blast_max_poll_attempts``, sleeping ``blast_poll_interval_seconds``
       between attempts -- both overridable, and both driven to ~0 in tests)
       until the embedded ``Status=`` reaches ``READY`` (or ``FAILED``/
       ``UNKNOWN``, which raise).
    3. ``CMD=Get&RID=...&FORMAT_TYPE=Text&ALIGNMENT_VIEW=Tabular`` fetches the
       final tab-delimited hit table once ready.

STRUCTURED ARGUMENTS ONLY -- no natural-language query layer. The original
Biomni paper's version of these tools accepts a free-text ``query: str`` and
relies on an LLM schema-parsing layer to turn it into the right endpoint
call; OSW has no such NL-to-query layer wired into this adapter tier. Every
tool below therefore requires the caller (an agent/DAG node with a known
accession/id/gene-or-compound-name/sequence, not a human typing prose) to
pass already-structured arguments -- see each method's docstring for its
exact argument names. Faking NL support here would mean either silently
mis-parsing free text into the wrong endpoint or quietly no-op'ing; neither
is acceptable, so it is not attempted.

No retry/backoff helper exists yet anywhere in this codebase's HTTP adapters
(a real, confirmed gap -- see ``docs/tools/db_adapter_catalog.md``); adding a
shared one is out of scope for this pass (a working adapter without retry
beats a half-finished one blocked on building that helper). ``blast_sequence``
already retries by protocol necessity (the poll loop above), which is not a
retry-on-failure policy -- it is BLAST's normal, documented, expected
control flow for an asynchronous search.
"""
import asyncio
import re
from typing import Any, Dict, List, Optional

import httpx

from src.infrastructure.mcp.server_registry import MCPServerRegistry

PRIDE_BASE_URL = "https://www.ebi.ac.uk/pride/ws/archive/v2"
GTOPDB_BASE_URL = "https://www.guidetopharmacology.org/services"
BLAST_BASE_URL = "https://blast.ncbi.nlm.nih.gov/Blast.cgi"

# Generous but bounded -- these are real, sometimes slow, third-party services.
# Applies per-HTTP-request; the overall BLAST poll budget is governed
# separately by `blast_poll_interval_seconds` * `blast_max_poll_attempts`.
DEFAULT_TIMEOUT_SECONDS = 30.0

# BLAST is fundamentally an async submit/poll/fetch protocol (see module
# docstring) -- these defaults bound the *total* wait for `blast_sequence`
# to roughly 3 minutes (60 attempts * 3s) before giving up with a clear
# error, rather than hanging indefinitely. Real BLAST searches against large
# databases can take longer than that; callers with such a workload should
# override both via the adapter constructor.
BLAST_POLL_INTERVAL_SECONDS = 3.0
BLAST_MAX_POLL_ATTEMPTS = 60

# BLAST program -> the database type it searches (nucleotide vs protein),
# used only to pick a sane default `database` when the caller doesn't supply
# one explicitly. `core_nt` is NCBI's current recommended name for the
# general nucleotide collection (the older bare `nt` alias still works but
# is being phased out); `nr` is the general non-redundant protein database.
_DEFAULT_BLAST_DATABASE_BY_PROGRAM = {
    "blastn": "core_nt",
    "blastp": "nr",
    "blastx": "nr",
    "tblastn": "core_nt",
    "tblastx": "core_nt",
}

# Biopython's `NCBIWWW.qblast` parses the BLAST Put response the same way:
# a plain `RID = <token>` line embedded in an HTML/comment wrapper.
_RID_PATTERN = re.compile(r"RID\s*=\s*(\S+)")
# The `CMD=Get&FORMAT_OBJECT=SearchInfo` polling response embeds a plain
# `Status=WAITING`/`Status=READY`/`Status=FAILED`/`Status=UNKNOWN` line.
_STATUS_PATTERN = re.compile(r"Status=(\w+)")

#: MCP tool name -> what each method below implements.
PROTEOMICS_PHARMA_TOOL_NAMES = ("query_pride", "query_gtopdb", "blast_sequence")


class ProteomicsPharmaAPIError(RuntimeError):
    """Raised when a proteomics/pharmacology REST API call fails: a non-2xx
    response (other than a clean 404/204 "not found"/"no results", which is
    reported as a more specific message) or a response body that doesn't
    have the shape this adapter expects."""


class ProteomicsPharmaDBAdapters:
    """Thin async wrapper around the real PRIDE / GtoPdb / NCBI BLAST REST APIs.

    An `httpx.AsyncClient` can be injected (tests use `httpx.MockTransport`,
    mirroring `BioDirectAdapters`'s test pattern); otherwise a fresh client is
    created per call, so callers never have to manage a client lifecycle.
    """

    def __init__(
        self,
        client: Optional[httpx.AsyncClient] = None,
        *,
        blast_poll_interval_seconds: float = BLAST_POLL_INTERVAL_SECONDS,
        blast_max_poll_attempts: int = BLAST_MAX_POLL_ATTEMPTS,
    ):
        self._client = client
        self._blast_poll_interval_seconds = blast_poll_interval_seconds
        self._blast_max_poll_attempts = blast_max_poll_attempts

    async def _get(self, url: str, *, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
        if self._client is not None:
            return await self._client.get(url, params=params)
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            return await client.get(url, params=params)

    async def _post(self, url: str, *, data: Optional[Dict[str, Any]] = None) -> httpx.Response:
        if self._client is not None:
            return await self._client.post(url, data=data)
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            return await client.post(url, data=data)

    # --- query_pride ---------------------------------------------------

    async def query_pride(self, arguments: Optional[Dict[str, Any]]) -> Any:
        """Queries the real PRIDE Archive (proteomics identifications) REST API.

        Structured arguments only (no free-text NL query -- see module
        docstring): pass exactly one of

        - ``accession`` (str): a PRIDE project accession (e.g. ``"PXD000001"``)
          for a direct project lookup -- returns a single JSON object.
        - ``keyword`` (str): a search term against PRIDE's project index --
          returns a JSON array of project objects. Optional ``page_size``
          (int, default 10) caps how many results come back.
        """
        args = arguments or {}
        accession = args.get("accession")
        keyword = args.get("keyword")

        if accession and str(accession).strip():
            accession = str(accession).strip()
            url = f"{PRIDE_BASE_URL}/projects/{accession}"
            response = await self._get(url)
            if response.status_code == 404:
                raise ProteomicsPharmaAPIError(f"PRIDE project '{accession}' was not found.")
            response.raise_for_status()

            try:
                data = response.json()
                if not isinstance(data, dict) or "accession" not in data:
                    raise ValueError("missing 'accession' field")
            except (ValueError, TypeError) as exc:
                raise ProteomicsPharmaAPIError(
                    f"PRIDE response for project '{accession}' did not contain the expected "
                    "project data."
                ) from exc
            return data

        if keyword and str(keyword).strip():
            keyword = str(keyword).strip()
            page_size = args.get("page_size", 10)
            url = f"{PRIDE_BASE_URL}/search/projects"
            response = await self._get(url, params={"keyword": keyword, "pageSize": page_size})
            response.raise_for_status()

            try:
                data = response.json()
            except ValueError as exc:
                raise ProteomicsPharmaAPIError("PRIDE search API returned a non-JSON response.") from exc
            if not isinstance(data, list):
                raise ProteomicsPharmaAPIError(
                    "PRIDE search API returned an unexpected response shape (expected a list)."
                )
            return data

        raise ValueError(
            "query_pride requires either a non-empty 'accession' (direct project lookup, e.g. "
            "'PXD000001') or a non-empty 'keyword' (project search) argument."
        )

    # --- query_gtopdb ----------------------------------------------------

    async def query_gtopdb(self, arguments: Optional[Dict[str, Any]]) -> Any:
        """Queries the real Guide to PHARMACOLOGY (GtoPdb) web services REST API.

        Structured arguments only (no free-text NL query -- see module
        docstring):

        - ``object_type`` (str, required): ``"target"`` or ``"ligand"``.
        - and exactly one of:
          - ``id`` (int/str): a GtoPdb ``targetId``/``ligandId`` for a direct
            lookup -- returns a single JSON object.
          - ``name`` (str): a name search (e.g. ``"EGFR"``, ``"aspirin"``) --
            returns a JSON array of matching objects (possibly empty).
        """
        args = arguments or {}
        object_type = str(args.get("object_type") or "").strip().lower()
        if object_type not in ("target", "ligand"):
            raise ValueError(
                "query_gtopdb requires an 'object_type' argument set to either 'target' or "
                "'ligand'."
            )
        collection = f"{object_type}s"
        id_field = f"{object_type}Id"

        object_id = args.get("id")
        name = args.get("name")
        has_id = object_id is not None and str(object_id).strip() != ""
        has_name = name is not None and str(name).strip() != ""
        if not has_id and not has_name:
            raise ValueError(
                "query_gtopdb requires either a non-empty 'id' (direct GtoPdb lookup) or a "
                "non-empty 'name' (search) argument."
            )

        if has_id:
            object_id = str(object_id).strip()
            url = f"{GTOPDB_BASE_URL}/{collection}/{object_id}"
            response = await self._get(url)
            if response.status_code in (404, 204):
                raise ProteomicsPharmaAPIError(
                    f"GtoPdb {object_type} id '{object_id}' was not found."
                )
            response.raise_for_status()

            try:
                data = response.json()
                if not isinstance(data, dict) or id_field not in data:
                    raise ValueError(f"missing '{id_field}' field")
            except (ValueError, TypeError) as exc:
                raise ProteomicsPharmaAPIError(
                    f"GtoPdb response for {object_type} id '{object_id}' did not contain the "
                    "expected data."
                ) from exc
            return data

        name = str(name).strip()
        url = f"{GTOPDB_BASE_URL}/{collection}"
        response = await self._get(url, params={"name": name})
        if response.status_code == 204:
            # Documented GtoPdb behaviour for "no results" -- a valid empty
            # outcome, not an error.
            return []
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as exc:
            raise ProteomicsPharmaAPIError("GtoPdb API returned a non-JSON response.") from exc
        if not isinstance(data, list):
            raise ProteomicsPharmaAPIError(
                "GtoPdb API returned an unexpected response shape (expected a list)."
            )
        return data

    # --- blast_sequence ----------------------------------------------------

    async def blast_sequence(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Identifies a sequence via the real NCBI BLAST Common URL API.

        Structured arguments only (no free-text NL query -- see module
        docstring):

        - ``sequence`` (str, required): a raw or FASTA-formatted nucleotide/
          protein sequence.
        - ``program`` (str, optional, default ``"blastn"``): one of
          ``blastn``/``blastp``/``blastx``/``tblastn``/``tblastx``.
        - ``database`` (str, optional): defaults to a sane database for
          ``program`` (``core_nt`` for nucleotide programs, ``nr`` for
          protein programs).
        - ``hitlist_size`` (int, optional, default 10): max hits requested.
        - ``email`` (str, optional): contact email passed through to NCBI,
          per their usage guidelines for programmatic access.

        This wraps BLAST's real submit-then-poll protocol end to end (see
        module docstring) and only returns once the search reaches `READY`
        or the poll budget (`blast_max_poll_attempts` *
        `blast_poll_interval_seconds`, both overridable via the constructor)
        is exhausted.
        """
        args = arguments or {}
        sequence = args.get("sequence")
        if not sequence or not str(sequence).strip():
            raise ValueError(
                "blast_sequence requires a non-empty 'sequence' argument (a raw or "
                "FASTA-formatted nucleotide/protein sequence)."
            )
        sequence = str(sequence).strip()

        program = str(args.get("program") or "blastn").strip().lower()
        if program not in _DEFAULT_BLAST_DATABASE_BY_PROGRAM:
            raise ValueError(
                "blast_sequence 'program' must be one of: "
                + ", ".join(sorted(_DEFAULT_BLAST_DATABASE_BY_PROGRAM))
            )

        database = args.get("database")
        database = str(database).strip() if database else _DEFAULT_BLAST_DATABASE_BY_PROGRAM[program]

        hitlist_size = args.get("hitlist_size", 10)

        put_data = {
            "CMD": "Put",
            "PROGRAM": program,
            "DATABASE": database,
            "QUERY": sequence,
            "HITLIST_SIZE": hitlist_size,
        }
        email = args.get("email")
        if email and str(email).strip():
            put_data["EMAIL"] = str(email).strip()

        put_response = await self._post(BLAST_BASE_URL, data=put_data)
        put_response.raise_for_status()

        rid_match = _RID_PATTERN.search(put_response.text)
        if not rid_match:
            raise ProteomicsPharmaAPIError(
                "NCBI BLAST did not return a request ID (RID) for the submitted sequence; the "
                "search could not be started."
            )
        rid = rid_match.group(1)

        status = None
        for _attempt in range(self._blast_max_poll_attempts):
            await asyncio.sleep(self._blast_poll_interval_seconds)
            status_response = await self._get(
                BLAST_BASE_URL, params={"CMD": "Get", "FORMAT_OBJECT": "SearchInfo", "RID": rid}
            )
            status_response.raise_for_status()
            status_match = _STATUS_PATTERN.search(status_response.text)
            status = status_match.group(1) if status_match else None

            if status == "READY":
                break
            if status == "FAILED":
                raise ProteomicsPharmaAPIError(f"NCBI BLAST search '{rid}' failed on the server side.")
            if status == "UNKNOWN":
                raise ProteomicsPharmaAPIError(
                    f"NCBI BLAST search '{rid}' is unknown to NCBI (the RID may have expired)."
                )
            # Anything else (typically "WAITING", or a response we couldn't
            # parse a status out of) -> keep polling until the attempt budget
            # is exhausted.
        else:
            raise ProteomicsPharmaAPIError(
                f"NCBI BLAST search '{rid}' did not complete within the polling budget "
                f"({self._blast_max_poll_attempts} attempts, "
                f"{self._blast_poll_interval_seconds}s apart)."
            )

        result_response = await self._get(
            BLAST_BASE_URL,
            params={"CMD": "Get", "RID": rid, "FORMAT_TYPE": "Text", "ALIGNMENT_VIEW": "Tabular"},
        )
        result_response.raise_for_status()
        content = result_response.text
        if not content.strip():
            raise ProteomicsPharmaAPIError(f"NCBI BLAST returned an empty result for search '{rid}'.")

        return {
            "rid": rid,
            "program": program,
            "database": database,
            "format": "tabular_text",
            "content": content,
        }


def register_proteomics_pharma_db_tools(
    registry: MCPServerRegistry, client: Optional[httpx.AsyncClient] = None
) -> List[str]:
    """Registers the proteomics/pharmacology DB tool handlers into `registry`.

    Returns the registered tool names. Always safe to call -- these APIs need
    no configuration/auth, so (unlike e.g. `register_skills`) there is no
    failure mode here worth guarding against at the call site.
    """
    adapters = ProteomicsPharmaDBAdapters(client)
    handlers = {
        "query_pride": adapters.query_pride,
        "query_gtopdb": adapters.query_gtopdb,
        "blast_sequence": adapters.blast_sequence,
    }
    for tool_name, handler in handlers.items():
        registry.register_server(tool_name, handler)
    return list(handlers.keys())
