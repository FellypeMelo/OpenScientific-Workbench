"""Genome-browser / expression-database DB adapters calling real public APIs
(Fase 2 DB-adapter catalog, "Genome browser / expression databases" group --
see ``docs/tools/db_adapter_catalog.md``).

Three tools, each a thin wrapper around one real, unauthenticated public REST
API, following the exact pattern established by
``infrastructure/mcp/bio_direct_adapters.py``:

- ``query_ucsc``: the UCSC Genome Browser REST API
  (https://api.genome.ucsc.edu). Two structured modes:
    - ``track`` supplied: ``GET /getData/track`` -- item data for that track,
      optionally scoped to a ``chrom``/``start``/``end`` region.
    - ``track`` omitted: ``GET /list/tracks`` -- every track available for a
      ``genome``.
  UCSC's API is documented (and verified live) to use ``;`` as the query
  parameter separator, not ``&`` -- see
  https://genome.ucsc.edu/goldenPath/help/api.html and the
  ``_ucsc_query_string`` helper below, which builds the query string by hand
  for exactly that reason (``httpx``'s own ``params=`` encoder always joins
  on ``&``).
- ``query_ensembl``: the Ensembl REST API
  (https://rest.ensembl.org/lookup/symbol/{species}/{symbol}) -- looks up a
  gene by its symbol.
- ``query_geo``: NCBI's Entrez eutils (https://eutils.ncbi.nlm.nih.gov)
  against the GEO DataSets database (``db=gds``) -- a two-hop
  ``esearch`` (term -> internal UIDs) then ``esummary`` (UIDs -> DataSet
  records) call, since GEO itself has no single-request JSON search
  endpoint.

Structured-args-only limitation
--------------------------------
The original Biomni paper's tool set accepts a free natural-language
``query`` string and relies on an LLM to translate it into the right
structured API call. OSW has no such NL-to-query translation layer wired
into this DB-adapter tier, so none of these three tools accept a free-text
``query`` argument -- callers must pass the same structured identifiers a
human would type into each database's own search form directly (a UCSC
``genome``/optional ``track``, an Ensembl gene ``symbol``, or a GEO
``search_term`` built the way NCBI's own Entrez query syntax expects, e.g.
``"GSE12345[Accession]"`` or plain keywords). Faking NL parsing here would
misrepresent capability this codebase does not have.

No retry/backoff exists anywhere in this codebase's HTTP adapters yet
(a confirmed, tracked gap -- see the catalog doc); adding a shared retry
helper was explicitly called out as optional/non-blocking for this pass, so
none is added here either, matching ``bio_direct_adapters.py``.
"""
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from src.infrastructure.config import settings
from src.infrastructure.mcp.server_registry import MCPServerRegistry

logger = logging.getLogger(__name__)

UCSC_BASE_URL = "https://api.genome.ucsc.edu"
ENSEMBL_BASE_URL = "https://rest.ensembl.org"
NCBI_EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Generous but bounded -- these are real, sometimes slow, third-party services.
DEFAULT_TIMEOUT_SECONDS = 30.0

EXPRESSION_BROWSER_TOOL_NAMES = (
    "query_ucsc",
    "query_ensembl",
    "query_geo",
)


class ExpressionBrowserAPIError(RuntimeError):
    """Raised when a real genome-browser/expression DB API call fails: a
    non-2xx response reporting a structured error body (UCSC's
    ``{"error": ...}``, Ensembl's ``{"error": ...}``), an unstructured
    non-2xx response (propagated instead as ``httpx.HTTPStatusError`` via
    ``raise_for_status()``, same convention as ``bio_direct_adapters.py``),
    or a 200 response body that doesn't have the shape this adapter
    expects."""


def _ucsc_query_string(params: Dict[str, Any]) -> str:
    """Builds a UCSC-API-style query string joined on ``;`` (not ``&``).

    Verified live against ``api.genome.ucsc.edu``: e.g.
    ``?genome=hg38;track=gold;chrom=chrM`` succeeds while relying on the
    default ``&`` join is not something this adapter risks -- UCSC's own
    docs are explicit about the ``;`` separator, so the query string is
    built here rather than handed to ``httpx``'s ``params=`` (which always
    joins on ``&``). ``None``-valued entries are dropped so optional
    arguments can be passed straight through without extra filtering at
    each call site.
    """
    return ";".join(
        f"{quote(str(key), safe='')}={quote(str(value), safe='')}"
        for key, value in params.items()
        if value is not None
    )


class ExpressionBrowserDBAdapters:
    """Thin async wrapper around the real UCSC/Ensembl/NCBI-eutils REST APIs.

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

    def _entrez_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Adds the configured NCBI contact email/API key (if any) to an
        eutils request -- both are optional courtesy/rate-limit params NCBI
        documents, never required for a request to succeed."""
        merged = dict(params)
        if settings.NCBI_EMAIL:
            merged["email"] = settings.NCBI_EMAIL
        if settings.NCBI_API_KEY:
            merged["api_key"] = settings.NCBI_API_KEY
        return merged

    @staticmethod
    def _parse_ucsc_response(response: httpx.Response, *, context: str) -> Dict[str, Any]:
        """Raises `ExpressionBrowserAPIError` for UCSC's structured
        ``{"error": ..., "statusCode": ...}`` bodies (UCSC reports both
        "bad genome" and "bad track" as HTTP 400 with this shape, never a
        404 -- verified live), otherwise falls back to
        ``response.raise_for_status()`` so an unstructured non-2xx (e.g. a
        plain-text 500) still propagates as `httpx.HTTPStatusError`, matching
        `bio_direct_adapters.py`'s convention."""
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = None
            if isinstance(body, dict) and body.get("error"):
                raise ExpressionBrowserAPIError(
                    f"UCSC API error for {context}: {body['error']}"
                )
            response.raise_for_status()

        try:
            data = response.json()
        except ValueError as exc:
            raise ExpressionBrowserAPIError(
                f"UCSC API returned a non-JSON response for {context}."
            ) from exc
        if not isinstance(data, dict):
            raise ExpressionBrowserAPIError(
                f"UCSC API returned an unexpected response shape for {context}."
            )
        return data

    async def query_ucsc(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Queries the real UCSC Genome Browser REST API (structured args
        only -- see module docstring).

        Required: ``genome`` (e.g. ``'hg38'``).
        Optional: ``track`` -- when supplied, fetches item data for that
        track (``/getData/track``), further optionally scoped by ``chrom``,
        ``start``, ``end``, and capped by ``max_items``
        (-> ``maxItemsOutput``). When omitted, lists every track available
        for ``genome`` instead (``/list/tracks``).
        """
        args = arguments or {}
        genome = args.get("genome")
        if not genome or not str(genome).strip():
            raise ValueError(
                "query_ucsc requires a non-empty 'genome' argument (e.g. 'hg38')."
            )
        genome = str(genome).strip()
        track = args.get("track")

        if track and str(track).strip():
            track = str(track).strip()
            params: Dict[str, Any] = {"genome": genome, "track": track}
            chrom = args.get("chrom")
            if chrom and str(chrom).strip():
                params["chrom"] = str(chrom).strip()
            if args.get("start") is not None:
                params["start"] = int(args["start"])
            if args.get("end") is not None:
                params["end"] = int(args["end"])
            if args.get("max_items") is not None:
                params["maxItemsOutput"] = int(args["max_items"])

            url = f"{UCSC_BASE_URL}/getData/track?{_ucsc_query_string(params)}"
            response = await self._get(url)
            data = self._parse_ucsc_response(
                response, context=f"track '{track}' on genome '{genome}'"
            )

            items = data.get(track)
            if not isinstance(items, list):
                raise ExpressionBrowserAPIError(
                    f"UCSC API response for track '{track}' on genome '{genome}' did "
                    "not contain the expected item list."
                )
            return {
                "genome": genome,
                "track": track,
                "chrom": data.get("chrom"),
                "start": data.get("start"),
                "end": data.get("end"),
                "items_returned": data.get("itemsReturned", len(items)),
                "items": items,
            }

        url = f"{UCSC_BASE_URL}/list/tracks?{_ucsc_query_string({'genome': genome})}"
        response = await self._get(url)
        data = self._parse_ucsc_response(response, context=f"genome '{genome}'")

        tracks = data.get(genome)
        if not isinstance(tracks, dict):
            raise ExpressionBrowserAPIError(
                f"UCSC API response listing tracks for genome '{genome}' did not "
                "contain the expected track map."
            )
        return {"genome": genome, "track_count": len(tracks), "tracks": tracks}

    async def query_ensembl(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Looks up a gene by symbol via the real Ensembl REST API
        (``/lookup/symbol/{species}/{symbol}``).

        Required: ``symbol`` (e.g. ``'BRCA2'``).
        Optional: ``species`` (default ``'homo_sapiens'``), ``expand``
        (bool, default ``False`` -- includes nested transcripts/exons when
        true).
        """
        args = arguments or {}
        symbol = args.get("symbol")
        if not symbol or not str(symbol).strip():
            raise ValueError(
                "query_ensembl requires a non-empty 'symbol' argument (e.g. 'BRCA2')."
            )
        symbol = str(symbol).strip()
        species = str(args.get("species") or "homo_sapiens").strip()
        expand = bool(args.get("expand", False))

        url = f"{ENSEMBL_BASE_URL}/lookup/symbol/{species}/{symbol}"
        params: Dict[str, Any] = {"content-type": "application/json"}
        if expand:
            params["expand"] = 1
        response = await self._get(url, params=params)

        if response.status_code == 400:
            message = None
            try:
                body = response.json()
            except ValueError:
                body = None
            if isinstance(body, dict) and body.get("error"):
                message = str(body["error"])
            raise ExpressionBrowserAPIError(
                f"Ensembl lookup for symbol '{symbol}' ({species}) failed"
                + (f": {message}" if message else ".")
            )
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as exc:
            raise ExpressionBrowserAPIError(
                f"Ensembl API returned a non-JSON response for symbol '{symbol}' "
                f"({species})."
            ) from exc
        if not isinstance(data, dict) or "id" not in data:
            raise ExpressionBrowserAPIError(
                f"Ensembl API response for symbol '{symbol}' ({species}) did not "
                "contain the expected gene data."
            )
        return data

    async def query_geo(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Searches NCBI GEO DataSets (``db=gds``) via the real NCBI Entrez
        eutils, structured-args only (see module docstring): ``esearch``
        (``search_term`` -> internal UIDs) followed by ``esummary``
        (UIDs -> DataSet records), since GEO has no single-request JSON
        search endpoint of its own.

        Required: ``search_term`` -- an NCBI Entrez query term, e.g.
        ``'GSE12345[Accession]'`` or free keywords like
        ``'breast cancer expression'`` (NCBI's own query syntax, not OSW
        natural-language parsing).
        Optional: ``retmax`` (default 20) -- max DataSet records to return.
        """
        args = arguments or {}
        search_term = args.get("search_term")
        if not search_term or not str(search_term).strip():
            raise ValueError(
                "query_geo requires a non-empty 'search_term' argument (e.g. "
                "'GSE12345[Accession]' or 'breast cancer expression')."
            )
        search_term = str(search_term).strip()
        retmax = int(args.get("retmax") or 20)

        search_params = self._entrez_params(
            {"db": "gds", "term": search_term, "retmode": "json", "retmax": retmax}
        )
        search_response = await self._get(f"{NCBI_EUTILS_BASE_URL}/esearch.fcgi", params=search_params)
        search_response.raise_for_status()
        try:
            search_data = search_response.json()
            idlist: List[str] = search_data["esearchresult"]["idlist"]
            total_count = search_data["esearchresult"].get("count")
        except (ValueError, KeyError, TypeError) as exc:
            raise ExpressionBrowserAPIError(
                f"NCBI GEO esearch response for '{search_term}' did not contain the "
                "expected result shape."
            ) from exc

        if not idlist:
            return {"search_term": search_term, "count": total_count, "records": []}

        summary_params = self._entrez_params({"db": "gds", "id": ",".join(idlist), "retmode": "json"})
        summary_response = await self._get(f"{NCBI_EUTILS_BASE_URL}/esummary.fcgi", params=summary_params)
        summary_response.raise_for_status()
        try:
            summary_data = summary_response.json()
            result = summary_data["result"]
            uids: List[str] = result["uids"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ExpressionBrowserAPIError(
                f"NCBI GEO esummary response for '{search_term}' did not contain the "
                "expected result shape."
            ) from exc

        records = [result[uid] for uid in uids if isinstance(result.get(uid), dict)]
        return {"search_term": search_term, "count": total_count, "records": records}


def register_expression_browser_db_tools(
    registry: MCPServerRegistry, client: Optional[httpx.AsyncClient] = None
) -> List[str]:
    """Registers the expression-browser DB tool handlers into `registry`.

    Returns the registered tool names. Always safe to call -- these APIs
    need no configuration/auth to function (the NCBI email/API key are
    optional courtesy/rate-limit params, not gates on functioning at all),
    so there is no failure mode here worth guarding against at the call
    site, matching `register_direct_bio_tools`.
    """
    adapters = ExpressionBrowserDBAdapters(client)
    handlers = {
        "query_ucsc": adapters.query_ucsc,
        "query_ensembl": adapters.query_ensembl,
        "query_geo": adapters.query_geo,
    }
    for tool_name, handler in handlers.items():
        registry.register_server(tool_name, handler)
    return list(handlers.keys())
