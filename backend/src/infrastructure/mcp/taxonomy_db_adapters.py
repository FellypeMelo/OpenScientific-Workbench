"""Direct taxonomy/ecology/paleontology DB adapters calling four real public
REST APIs, following the same "direct" pattern as `bio_direct_adapters.py`
(`BioDirectAdapters` / `register_direct_bio_tools`) rather than the dormant
generic MCP-gateway path (`jsonrpc_client.py` + `bio_adapters.py`).

Tools implemented here (see `docs/tools/db_adapter_catalog.md`, "Taxonomy /
ecology / paleontology databases"):

- ``query_iucn`` -- IUCN Red List API v4 (species conservation status): ``GET
  https://api.iucnredlist.org/api/v4/taxa/scientific_name?genus_name=...&species_name=...``,
  requires a Bearer token (see `IUCN_API_TOKEN` in `infrastructure/config.py`).
- ``query_paleobiology`` -- Paleobiology Database (PBDB) Data Service: ``GET
  https://paleobiodb.org/data1.2/taxa/single.json?name=...`` -- fossil taxon
  lookup by name.
- ``query_worms`` -- World Register of Marine Species (WoRMS) REST API: ``GET
  https://www.marinespecies.org/rest/AphiaRecordsByName/{name}`` -- marine
  taxonomy lookup by scientific name.
- ``query_mpd`` -- Mouse Phenome Database (MPD) phenotype API: ``GET
  https://phenome.jax.org/api/pheno/strainmeans/{measnum}`` -- unadjusted
  per-strain phenotype means for one or more MPD measure numbers.

Structured-args-only limitation (same as `bio_direct_adapters.py` and every
other `*_db_adapters.py` module in this codebase): the Biomni paper these
tool names are drawn from describes an NL-prompt-to-query layer in front of
each of these APIs. OSW has no such NL-to-structured-query LLM layer wired
into this adapter tier, so none of these four tools accept a free-text
``query`` string -- each requires the same structured identifiers a human
would type into the API's own query form directly (a scientific/taxon name
split as the API expects, or one or more numeric measure IDs). Callers that
want NL-driven lookups must resolve the structured identifier themselves
(e.g. via an LLM turn upstream of the tool call) before invoking these
tools.

Only ``query_iucn`` needs configuration (a Bearer token -- see
`IUCN_API_TOKEN`); the other three are public, unauthenticated REST APIs.

No retry/backoff exists yet in this codebase's HTTP adapters (a known,
tracked gap -- see `docs/tools/db_adapter_catalog.md`'s implementation
notes); these four adapters intentionally match that same convention
(single attempt, `DEFAULT_TIMEOUT_SECONDS = 30.0`) rather than half-wiring
retry logic for only one file in the codebase.
"""
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from src.infrastructure.config import settings
from src.infrastructure.mcp.server_registry import MCPServerRegistry

logger = logging.getLogger(__name__)

IUCN_BASE_URL = "https://api.iucnredlist.org/api/v4"
PBDB_BASE_URL = "https://paleobiodb.org/data1.2"
WORMS_BASE_URL = "https://www.marinespecies.org/rest"
MPD_BASE_URL = "https://phenome.jax.org/api"

# Generous but bounded -- these are real, sometimes slow, third-party services
# (matches `bio_direct_adapters.py`'s convention exactly).
DEFAULT_TIMEOUT_SECONDS = 30.0

#: MCP tool name -> what this module registers. New tool names (unlike
#: `bio_direct_adapters.py`'s `DIRECT_BIO_TOOL_NAMES`, which mirrors three
#: pre-existing names), not a drop-in replacement for anything.
TAXONOMY_DB_TOOL_NAMES = (
    "query_iucn",
    "query_paleobiology",
    "query_worms",
    "query_mpd",
)


class TaxonomyAPIError(RuntimeError):
    """Raised when a taxonomy/ecology/paleontology REST API call fails: a
    non-2xx response (other than a clean "not found" case, which is reported
    as a more specific message) or a response body that doesn't have the
    shape this adapter expects."""


class TaxonomyDBAdapters:
    """Thin async wrapper around four real public taxonomy/ecology/
    paleontology REST APIs (IUCN Red List, PBDB, WoRMS, MPD).

    An `httpx.AsyncClient` can be injected (tests use `httpx.MockTransport`,
    mirroring `BioDirectAdapters`'s test pattern); otherwise a fresh client is
    created per call, so callers never have to manage a client lifecycle.

    `iucn_api_token` can likewise be injected directly (used by tests, and by
    any future caller that wants a token other than the process-wide
    `settings.IUCN_API_TOKEN`); when omitted it falls back to
    `settings.IUCN_API_TOKEN`, which is `None` unless configured via env/
    `.env`.
    """

    def __init__(
        self,
        client: Optional[httpx.AsyncClient] = None,
        iucn_api_token: Optional[str] = None,
    ):
        self._client = client
        self._iucn_api_token = (
            iucn_api_token if iucn_api_token is not None else settings.IUCN_API_TOKEN
        )

    async def _get(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> httpx.Response:
        if self._client is not None:
            return await self._client.get(url, params=params, headers=headers)
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            return await client.get(url, params=params, headers=headers)

    async def query_iucn(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Fetches a species' conservation-status assessments from the real
        IUCN Red List API v4 (`taxa/scientific_name`).

        Structured args: ``genus_name`` and ``species_name`` (both required,
        e.g. ``{"genus_name": "Panthera", "species_name": "leo"}`` -- not a
        single combined "scientific name" string, matching the real API's own
        two separate query parameters). Optional: ``infra_name``,
        ``subpopulation_name`` (passed through when given).
        """
        args = arguments or {}
        genus_name = args.get("genus_name")
        species_name = args.get("species_name")
        if not genus_name or not str(genus_name).strip():
            raise ValueError(
                "query_iucn requires a non-empty 'genus_name' argument (e.g. 'Panthera')."
            )
        if not species_name or not str(species_name).strip():
            raise ValueError(
                "query_iucn requires a non-empty 'species_name' argument (e.g. 'leo')."
            )
        genus_name = str(genus_name).strip()
        species_name = str(species_name).strip()

        if not self._iucn_api_token:
            raise ValueError(
                "query_iucn requires an IUCN Red List API token. Set IUCN_API_TOKEN "
                "in the environment/.env (request one at "
                "https://api.iucnredlist.org/users/sign_up)."
            )

        params: Dict[str, Any] = {"genus_name": genus_name, "species_name": species_name}
        infra_name = args.get("infra_name")
        if infra_name and str(infra_name).strip():
            params["infra_name"] = str(infra_name).strip()
        subpopulation_name = args.get("subpopulation_name")
        if subpopulation_name and str(subpopulation_name).strip():
            params["subpopulation_name"] = str(subpopulation_name).strip()

        url = f"{IUCN_BASE_URL}/taxa/scientific_name"
        response = await self._get(
            url, params=params, headers={"Authorization": f"Bearer {self._iucn_api_token}"}
        )
        if response.status_code == 404:
            raise TaxonomyAPIError(
                f"IUCN Red List has no taxon matching '{genus_name} {species_name}'."
            )
        response.raise_for_status()

        try:
            data = response.json()
            assessments = data["assessments"]
            if not isinstance(assessments, list):
                raise TypeError("'assessments' was not a list")
        except (ValueError, KeyError, TypeError) as exc:
            raise TaxonomyAPIError(
                f"IUCN Red List response for '{genus_name} {species_name}' did not contain "
                "the expected assessment data."
            ) from exc

        return {
            "genus_name": genus_name,
            "species_name": species_name,
            "taxon": data.get("taxon"),
            "assessments": assessments,
        }

    async def query_paleobiology(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Fetches a single fossil taxon record from the real Paleobiology
        Database (PBDB) Data Service (`taxa/single.json`).

        Structured args: ``taxon_name`` (required, e.g. 'Tyrannosaurus').
        Optional: ``show`` (a PBDB data-block name, or list of them, e.g.
        ``["attr", "app"]`` -- passed straight through as PBDB's own `show`
        parameter).
        """
        args = arguments or {}
        taxon_name = args.get("taxon_name")
        if not taxon_name or not str(taxon_name).strip():
            raise ValueError(
                "query_paleobiology requires a non-empty 'taxon_name' argument "
                "(e.g. 'Tyrannosaurus')."
            )
        taxon_name = str(taxon_name).strip()

        # `vocab=pbdb` requests full descriptive field names (`taxon_name`,
        # `taxon_rank`, ...) instead of PBDB's default 3-character compact
        # codes (`nam`, `rnk`, ...) -- much more usable for a downstream tool
        # consumer (an LLM or human) than compact codes would be.
        params: Dict[str, Any] = {"name": taxon_name, "vocab": "pbdb"}
        show = args.get("show")
        if show:
            if isinstance(show, (list, tuple)):
                show = ",".join(str(s).strip() for s in show if str(s).strip())
            params["show"] = str(show).strip()

        url = f"{PBDB_BASE_URL}/taxa/single.json"
        response = await self._get(url, params=params)
        if response.status_code == 404:
            raise TaxonomyAPIError(f"Paleobiology Database has no taxon matching '{taxon_name}'.")
        response.raise_for_status()

        try:
            data = response.json()
            records = data["records"]
            if not isinstance(records, list) or not records:
                raise TypeError("'records' was missing/empty")
        except (ValueError, KeyError, TypeError) as exc:
            raise TaxonomyAPIError(
                f"Paleobiology Database response for '{taxon_name}' did not contain the "
                "expected taxon record."
            ) from exc

        return records[0]

    async def query_worms(
        self, arguments: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Fetches marine-taxonomy records from the real World Register of
        Marine Species (WoRMS) REST API (`AphiaRecordsByName`).

        Structured args: ``scientific_name`` (required, e.g. 'Solea solea').
        Optional: ``like`` (bool, default `False` -- exact match vs. SQL
        `LIKE`-style prefix match), ``marine_only`` (bool, default `True`).
        """
        args = arguments or {}
        scientific_name = args.get("scientific_name")
        if not scientific_name or not str(scientific_name).strip():
            raise ValueError(
                "query_worms requires a non-empty 'scientific_name' argument "
                "(e.g. 'Solea solea')."
            )
        scientific_name = str(scientific_name).strip()
        like = bool(args.get("like", False))
        marine_only = bool(args.get("marine_only", True))

        url = f"{WORMS_BASE_URL}/AphiaRecordsByName/{quote(scientific_name, safe='')}"
        params = {"like": "true" if like else "false", "marine_only": "true" if marine_only else "false"}
        response = await self._get(url, params=params)
        # WoRMS reports "no match" either as an HTTP 204 (no body) or, on
        # more recent API versions, an HTTP 200 with an empty JSON array --
        # both are handled below (204 here, empty-list after parsing).
        if response.status_code == 404 or response.status_code == 204:
            raise TaxonomyAPIError(f"WoRMS has no record matching '{scientific_name}'.")
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as exc:
            raise TaxonomyAPIError("WoRMS API returned a non-JSON response.") from exc
        if not isinstance(data, list):
            raise TaxonomyAPIError("WoRMS API returned an unexpected response shape (expected a list).")
        if not data:
            raise TaxonomyAPIError(f"WoRMS has no record matching '{scientific_name}'.")

        return data

    async def query_mpd(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Fetches unadjusted per-strain phenotype means from the real Mouse
        Phenome Database (MPD) API (`pheno/strainmeans/{selector}`).

        Structured args: ``measnum`` (required -- an MPD measure number, or a
        list/comma-separated string of them, e.g. `2908` or `"2908,2909"` or
        `[2908, 2909]`).
        """
        args = arguments or {}
        raw_measnum = args.get("measnum")
        if isinstance(raw_measnum, (list, tuple)):
            measnums = [str(m).strip() for m in raw_measnum if str(m).strip()]
        elif raw_measnum is None:
            measnums = []
        else:
            measnums = [s.strip() for s in str(raw_measnum).split(",") if s.strip()]
        if not measnums:
            raise ValueError(
                "query_mpd requires a non-empty 'measnum' argument (an MPD measure "
                "number, or a list/comma-separated string of them, e.g. 2908)."
            )
        selector = ",".join(measnums)

        url = f"{MPD_BASE_URL}/pheno/strainmeans/{selector}"
        response = await self._get(url)
        if response.status_code == 404:
            raise TaxonomyAPIError(
                f"Mouse Phenome Database has no strain-means data for measnum(s) '{selector}'."
            )
        response.raise_for_status()

        try:
            data = response.json()
            strainmeans = data["strainmeans"]
            if not isinstance(strainmeans, list):
                raise TypeError("'strainmeans' was not a list")
        except (ValueError, KeyError, TypeError) as exc:
            raise TaxonomyAPIError(
                f"Mouse Phenome Database response for measnum(s) '{selector}' did not "
                "contain the expected 'strainmeans' data."
            ) from exc

        return {"measnum": selector, "count": data.get("count", len(strainmeans)), "strainmeans": strainmeans}


def register_taxonomy_db_tools(
    registry: MCPServerRegistry,
    client: Optional[httpx.AsyncClient] = None,
    iucn_api_token: Optional[str] = None,
) -> List[str]:
    """Registers the taxonomy/ecology/paleontology DB tool handlers into
    `registry`.

    Returns the registered tool names. Always safe to call for
    `query_paleobiology`/`query_worms`/`query_mpd` (no configuration/auth
    needed); `query_iucn` itself raises a clear `ValueError` at call time
    (not at registration time) if no IUCN API token is configured, matching
    how `register_direct_bio_tools` defers all failure modes to call time
    rather than guarding registration.
    """
    adapters = TaxonomyDBAdapters(client, iucn_api_token=iucn_api_token)
    handlers: Dict[str, Any] = {
        "query_iucn": adapters.query_iucn,
        "query_paleobiology": adapters.query_paleobiology,
        "query_worms": adapters.query_worms,
        "query_mpd": adapters.query_mpd,
    }
    for tool_name, handler in handlers.items():
        registry.register_server(tool_name, handler)
    return list(handlers.keys())
