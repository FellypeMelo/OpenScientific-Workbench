"""Pathway / interaction / regulatory-database MCP adapters -- real HTTP calls to
public KEGG/STRING/Reactome/RegulomeDB/JASPAR/ENCODE-SCREEN/ReMap REST APIs.

This module follows the exact conventions established by
``bio_direct_adapters.py`` (RF-004): a thin class wrapping an optional
injected ``httpx.AsyncClient``, one async method per tool that validates its
own required arguments (raising ``ValueError`` on missing/empty input),
raises a domain-specific ``PathwayRegulatoryAPIError(RuntimeError)`` on a
bad/unexpected upstream response shape, and a module-level
``register_pathway_regulatory_db_tools(registry, client=None)`` that wires
every tool name into an ``MCPServerRegistry``.

Endpoints covered (8 tools, per ``docs/tools/db_adapter_catalog.md``'s
"Pathway / interaction / regulatory databases" section):

- ``query_kegg`` -- KEGG REST API (``GET https://rest.kegg.jp/<operation>/<target>``).
- ``query_stringdb`` -- STRING API methods *other than* the network-fetch case
  (already covered by ``bio_direct_adapters.get_string_interactions``):
  ``get_string_ids``, ``interaction_partners``, ``homology``,
  ``homology_best``, ``enrichment``, ``functional_annotation``,
  ``ppi_enrichment``, ``version``.
- ``query_reactome`` -- Reactome ContentService (``data/query/{stId}`` direct
  lookup, or ``search/query`` free-text search).
- ``query_regulomedb`` -- RegulomeDB regulatory annotation of a variant
  (rsID) or genomic coordinate range.
- ``query_jaspar`` -- JASPAR REST API (direct matrix lookup by ID, or a
  filtered search over transcription-factor binding profiles).
- ``region_to_ccre_screen`` -- ENCODE SCREEN candidate cis-regulatory
  elements (cCREs) intersecting a genomic region.
- ``get_genes_near_ccre`` -- ENCODE SCREEN k-nearest genes to a cCRE.
- ``query_remap`` -- ReMap transcription-factor ChIP-seq binding peaks in a
  genomic region.

STRUCTURED ARGUMENTS ONLY: the original Biomni paper's tools of this shape
accept a free natural-language ``prompt`` and use an LLM to translate it into
a concrete API call. OSW has no NL-to-query LLM layer wired into this
adapter tier, so that mode is intentionally NOT implemented here -- every
tool below instead requires the caller to already supply structured
arguments (an accession/stable ID/gene or TF symbol/genomic coordinates, as
appropriate to that database), matching the "direct endpoint" mode Biomni's
own tools already support as a non-LLM fallback. Do not attempt to fake NL
parsing on top of this.
"""
import logging
from typing import Any, Dict, List, Optional, Union

import httpx

from src.infrastructure.mcp.server_registry import MCPServerRegistry

logger = logging.getLogger(__name__)

KEGG_BASE_URL = "https://rest.kegg.jp"
STRING_API_BASE_URL = "https://string-db.org/api"
REACTOME_CONTENT_BASE_URL = "https://reactome.org/ContentService"
REGULOMEDB_BASE_URL = "https://regulomedb.org"
JASPAR_BASE_URL = "https://jaspar.elixir.no/api/v1"
# ENCODE SCREEN's "beta" API host is, in practice, the stable public data
# service behind https://screen.encodeproject.org's own UI (confirmed live:
# POSTing malformed bodies to both paths below returns a 500 from the
# service itself, not a 404 -- i.e. the routes exist), and is the exact
# endpoint Biomni's own `region_to_ccre_screen`/`get_genes_near_ccre` tools
# call. There is no documented, versioned "v1" alternative to pin to instead.
SCREEN_DATAWS_BASE_URL = "https://screen-beta-api.wenglab.org/dataws"
REMAP_BASE_URL = "https://remap-rest.univ-amu.fr/api/V1"

# Generous but bounded -- these are real, sometimes slow, third-party services.
DEFAULT_TIMEOUT_SECONDS = 30.0

KEGG_OPERATIONS = {"info", "list", "find", "get", "conv", "link"}

#: STRING methods that need an `identifiers` argument. `network` (the
#: interaction-graph fetch) is intentionally excluded -- that case is already
#: covered by `bio_direct_adapters.get_string_interactions`.
STRING_METHODS_REQUIRING_IDENTIFIERS = {
    "get_string_ids",
    "interaction_partners",
    "homology",
    "homology_best",
    "enrichment",
    "functional_annotation",
    "ppi_enrichment",
}
STRING_METHODS = STRING_METHODS_REQUIRING_IDENTIFIERS | {"version"}

JASPAR_SEARCH_PARAMS = {
    "search",
    "name",
    "collection",
    "tax_group",
    "tax_id",
    "tf_class",
    "tf_family",
    "data_type",
    "page",
    "page_size",
    "release",
}

REMAP_DATATYPES = {"all", "nr", "crm"}

#: MCP tool name -> registered handler, see `register_pathway_regulatory_db_tools`.
PATHWAY_REGULATORY_DB_TOOL_NAMES = (
    "query_kegg",
    "query_stringdb",
    "query_reactome",
    "query_regulomedb",
    "query_jaspar",
    "region_to_ccre_screen",
    "get_genes_near_ccre",
    "query_remap",
)


class PathwayRegulatoryAPIError(RuntimeError):
    """Raised when a pathway/regulatory-database REST API call fails: a
    non-2xx response (other than a clean 404, which is reported as a more
    specific `not found`/`no results` message) or a response body that
    doesn't have the shape this adapter expects."""


class PathwayRegulatoryDBAdapters:
    """Thin async wrapper around the real KEGG/STRING/Reactome/RegulomeDB/
    JASPAR/ENCODE-SCREEN/ReMap public REST APIs.

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

    async def _post(self, url: str, *, json: Optional[Dict[str, Any]] = None) -> httpx.Response:
        if self._client is not None:
            return await self._client.post(url, json=json)
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            return await client.post(url, json=json)

    # --- query_kegg ---------------------------------------------------

    async def query_kegg(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Queries the real KEGG REST API (pathways, genes, compounds, ...).

        Structured arguments (no natural-language prompt parsing):
        - `operation` (required): one of `info`, `list`, `find`, `get`,
          `conv`, `link`.
        - `target` (required): the KEGG REST path segment(s) after the
          operation, e.g. `'hsa:7157'` (a gene), `'pathway/hsa'` (human
          pathways), `'genes/shiga+toxin'` (a `find` query).
        - `option` (optional): a third path segment, e.g. `'aaseq'` for
          `get`.
        """
        args = arguments or {}
        operation = args.get("operation")
        if not operation or str(operation).strip().lower() not in KEGG_OPERATIONS:
            raise ValueError(
                "query_kegg requires an 'operation' argument, one of: "
                f"{sorted(KEGG_OPERATIONS)}."
            )
        operation = str(operation).strip().lower()

        target = args.get("target")
        if not target or not str(target).strip():
            raise ValueError(
                "query_kegg requires a non-empty 'target' argument -- the KEGG REST "
                "path segment(s) after the operation (e.g. 'hsa:7157' for a gene, "
                "'pathway/hsa' for human pathways)."
            )
        target = str(target).strip().strip("/")

        path_segments = [operation, target]
        option = args.get("option")
        if option and str(option).strip():
            option = str(option).strip().strip("/")
            path_segments.append(option)
        else:
            option = None

        url = "/".join([KEGG_BASE_URL, *path_segments])
        response = await self._get(url)
        if response.status_code == 404:
            raise PathwayRegulatoryAPIError(
                f"KEGG '{operation}' query for '{target}' returned no results (404)."
            )
        response.raise_for_status()

        text = response.text
        if not text.strip():
            raise PathwayRegulatoryAPIError(
                f"KEGG '{operation}' query for '{target}' returned an empty response."
            )
        return {"operation": operation, "target": target, "option": option, "result": text}

    # --- query_stringdb -------------------------------------------------

    async def query_stringdb(self, arguments: Optional[Dict[str, Any]]) -> Any:
        """Queries real STRING API methods other than the network-fetch case
        (see `bio_direct_adapters.get_string_interactions` for that one).

        Structured arguments:
        - `method` (required): one of `STRING_METHODS` (e.g.
          `'get_string_ids'`, `'enrichment'`, `'version'`).
        - `identifiers` (required for every method except `'version'`): a
          gene/protein identifier, or a list of them.
        - `species` (optional, default 9606 -- human).
        - `species_b` (optional): a second species taxon ID, used by
          `'homology_best'` cross-species queries.
        """
        args = arguments or {}
        method = args.get("method")
        if not method or str(method).strip() not in STRING_METHODS:
            raise ValueError(
                "query_stringdb requires a 'method' argument, one of: "
                f"{sorted(STRING_METHODS)} (use 'get_string_interactions' for the "
                "network-fetch case)."
            )
        method = str(method).strip()

        params: Dict[str, Any] = {}
        if method in STRING_METHODS_REQUIRING_IDENTIFIERS:
            raw_identifiers: Optional[Union[str, List[str]]] = args.get("identifiers")
            identifiers: List[str] = (
                [raw_identifiers] if isinstance(raw_identifiers, str) else list(raw_identifiers or [])
            )
            identifiers = [str(i).strip() for i in identifiers if str(i).strip()]
            if not identifiers:
                raise ValueError(
                    f"query_stringdb method '{method}' requires a non-empty 'identifiers' "
                    "argument (a gene/protein identifier, or a list of them)."
                )
            # Same STRING multi-identifier separator convention as
            # `bio_direct_adapters.get_string_interactions`.
            params["identifiers"] = "\r".join(identifiers)
            params["species"] = args.get("species", 9606)
            species_b = args.get("species_b")
            if species_b:
                params["species_b"] = species_b

        url = f"{STRING_API_BASE_URL}/json/{method}"
        response = await self._get(url, params=params)
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as exc:
            raise PathwayRegulatoryAPIError(
                f"STRING API method '{method}' returned a non-JSON response."
            ) from exc
        if not isinstance(data, (list, dict)):
            raise PathwayRegulatoryAPIError(
                f"STRING API method '{method}' returned an unexpected response shape "
                "(expected a list or object)."
            )
        return data

    # --- query_reactome ---------------------------------------------------

    async def query_reactome(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Queries the real Reactome ContentService REST API for pathway data.

        Structured arguments (exactly one of the following is required):
        - `id`: a Reactome stable identifier for a direct entity lookup
          (e.g. `'R-HSA-73894'`).
        - `query`: a free-text search term (e.g. `'DNA repair'`); optionally
          paired with `species` (default `'Homo sapiens'`).
        """
        args = arguments or {}
        stable_id = args.get("id")
        search_query = args.get("query")

        if stable_id and str(stable_id).strip():
            stable_id = str(stable_id).strip()
            url = f"{REACTOME_CONTENT_BASE_URL}/data/query/{stable_id}"
            response = await self._get(url)
            if response.status_code == 404:
                raise PathwayRegulatoryAPIError(f"Reactome entity '{stable_id}' was not found.")
            response.raise_for_status()
            try:
                data = response.json()
            except ValueError as exc:
                raise PathwayRegulatoryAPIError(
                    f"Reactome response for entity '{stable_id}' was not valid JSON."
                ) from exc
            if not isinstance(data, dict) or "dbId" not in data:
                raise PathwayRegulatoryAPIError(
                    f"Reactome response for entity '{stable_id}' did not contain the "
                    "expected entity data."
                )
            return data

        if search_query and str(search_query).strip():
            search_query = str(search_query).strip()
            url = f"{REACTOME_CONTENT_BASE_URL}/search/query"
            params = {"query": search_query, "species": args.get("species", "Homo sapiens")}
            response = await self._get(url, params=params)
            response.raise_for_status()
            try:
                data = response.json()
            except ValueError as exc:
                raise PathwayRegulatoryAPIError(
                    f"Reactome search for '{search_query}' did not return valid JSON."
                ) from exc
            if not isinstance(data, dict):
                raise PathwayRegulatoryAPIError(
                    f"Reactome search for '{search_query}' returned an unexpected response "
                    "shape (expected an object)."
                )
            return data

        raise ValueError(
            "query_reactome requires either a non-empty 'id' (Reactome stable identifier, "
            "e.g. 'R-HSA-73894') or 'query' (free-text search term) argument."
        )

    # --- query_regulomedb ---------------------------------------------

    async def query_regulomedb(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Queries the real RegulomeDB API for regulatory annotation of a
        variant or genomic region.

        Structured arguments:
        - `region` (required): a dbSNP rsID (e.g. `'rs35675666'`) or a
          `'chrom:start-end'` coordinate range (e.g.
          `'chr11:5246919-5246919'`).
        - `genome` (optional, default `'GRCh38'`).
        """
        args = arguments or {}
        region = args.get("region")
        if not region or not str(region).strip():
            raise ValueError(
                "query_regulomedb requires a non-empty 'region' argument -- a dbSNP "
                "rsID (e.g. 'rs35675666') or a 'chrom:start-end' coordinate range "
                "(e.g. 'chr11:5246919-5246919')."
            )
        region = str(region).strip()
        genome = args.get("genome", "GRCh38")

        url = f"{REGULOMEDB_BASE_URL}/regulome-search/"
        params = {"regions": region, "genome": genome, "format": "json"}
        response = await self._get(url, params=params)
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as exc:
            raise PathwayRegulatoryAPIError(
                f"RegulomeDB query for '{region}' did not return valid JSON."
            ) from exc
        if not isinstance(data, dict) or "@graph" not in data:
            raise PathwayRegulatoryAPIError(
                f"RegulomeDB response for '{region}' did not contain the expected "
                "'@graph' data."
            )
        return data

    # --- query_jaspar -----------------------------------------------------

    async def query_jaspar(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Queries the real JASPAR REST API for transcription-factor binding
        profiles.

        Structured arguments (exactly one mode is required):
        - `matrix_id`: a direct profile lookup by JASPAR matrix ID (e.g.
          `'MA0002.2'`).
        - one or more of `JASPAR_SEARCH_PARAMS` (e.g. `name`, `tax_id`,
          `collection`) to search/filter profiles instead.
        """
        args = arguments or {}
        matrix_id = args.get("matrix_id")
        if matrix_id and str(matrix_id).strip():
            matrix_id = str(matrix_id).strip()
            url = f"{JASPAR_BASE_URL}/matrix/{matrix_id}/"
            response = await self._get(url)
            if response.status_code == 404:
                raise PathwayRegulatoryAPIError(f"JASPAR matrix '{matrix_id}' was not found.")
            response.raise_for_status()
            try:
                data = response.json()
            except ValueError as exc:
                raise PathwayRegulatoryAPIError(
                    f"JASPAR response for matrix '{matrix_id}' was not valid JSON."
                ) from exc
            if not isinstance(data, dict) or "matrix_id" not in data:
                raise PathwayRegulatoryAPIError(
                    f"JASPAR response for matrix '{matrix_id}' did not contain the "
                    "expected profile data."
                )
            return data

        search_params = {
            key: value
            for key, value in args.items()
            if key in JASPAR_SEARCH_PARAMS and value is not None and str(value).strip()
        }
        if not search_params:
            raise ValueError(
                "query_jaspar requires either a non-empty 'matrix_id' (direct profile "
                "lookup, e.g. 'MA0002.2') or at least one search filter "
                f"({sorted(JASPAR_SEARCH_PARAMS)})."
            )
        url = f"{JASPAR_BASE_URL}/matrix/"
        response = await self._get(url, params=search_params)
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError as exc:
            raise PathwayRegulatoryAPIError("JASPAR search did not return valid JSON.") from exc
        if not isinstance(data, dict) or "results" not in data:
            raise PathwayRegulatoryAPIError(
                "JASPAR search response did not contain the expected 'results' data."
            )
        return data

    # --- region_to_ccre_screen ---------------------------------------

    async def region_to_ccre_screen(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Given genomic coordinates, retrieves intersecting ENCODE SCREEN
        candidate cis-regulatory elements (cCREs) from the real SCREEN API.

        Structured arguments:
        - `chrom` (required): chromosome, e.g. `'chr12'`.
        - `start`, `end` (required): integer genomic coordinates.
        - `assembly` (optional, default `'GRCh38'`).
        """
        args = arguments or {}
        chrom = args.get("chrom")
        if not chrom or not str(chrom).strip():
            raise ValueError(
                "region_to_ccre_screen requires a non-empty 'chrom' argument (e.g. 'chr12')."
            )
        start, end = args.get("start"), args.get("end")
        if start is None or end is None:
            raise ValueError(
                "region_to_ccre_screen requires integer 'start' and 'end' genomic "
                "coordinate arguments."
            )
        try:
            start_int, end_int = int(start), int(end)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "region_to_ccre_screen's 'start'/'end' arguments must be integers."
            ) from exc

        chrom = str(chrom).strip()
        assembly = args.get("assembly", "GRCh38")
        payload = {
            "assembly": assembly,
            "coord_chrom": chrom,
            "coord_start": start_int,
            "coord_end": end_int,
        }
        url = f"{SCREEN_DATAWS_BASE_URL}/cre_table"
        response = await self._post(url, json=payload)
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as exc:
            raise PathwayRegulatoryAPIError(
                f"SCREEN cCRE lookup for '{chrom}:{start_int}-{end_int}' did not return "
                "valid JSON."
            ) from exc
        if isinstance(data, dict) and "errors" in data:
            raise PathwayRegulatoryAPIError(f"SCREEN API returned an error: {data['errors']}")
        if not isinstance(data, dict) or "cres" not in data:
            raise PathwayRegulatoryAPIError(
                f"SCREEN response for '{chrom}:{start_int}-{end_int}' did not contain the "
                "expected 'cres' data."
            )
        return data

    # --- get_genes_near_ccre ------------------------------------------

    async def get_genes_near_ccre(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Given a cCRE, returns the k nearest genes (sorted by distance)
        from the real SCREEN API.

        Structured arguments:
        - `accession` (required): the ENCODE cCRE accession, e.g.
          `'EH38E1516980'`.
        - `chromosome` (required): the cCRE's chromosome, e.g. `'chr12'`.
        - `assembly` (optional, default `'GRCh38'`).
        - `k` (optional, default 10): number of nearby genes to return.
        """
        args = arguments or {}
        accession = args.get("accession")
        if not accession or not str(accession).strip():
            raise ValueError(
                "get_genes_near_ccre requires a non-empty 'accession' argument (an "
                "ENCODE cCRE accession, e.g. 'EH38E1516980')."
            )
        accession = str(accession).strip()

        chromosome = args.get("chromosome")
        if not chromosome or not str(chromosome).strip():
            raise ValueError(
                "get_genes_near_ccre requires a non-empty 'chromosome' argument "
                "(e.g. 'chr12')."
            )
        chromosome = str(chromosome).strip()

        assembly = args.get("assembly", "GRCh38")
        k = args.get("k", 10)
        try:
            k = int(k)
        except (TypeError, ValueError) as exc:
            raise ValueError("get_genes_near_ccre's 'k' argument must be an integer.") from exc

        payload = {"accession": accession, "assembly": assembly, "coord_chrom": chromosome}
        url = f"{SCREEN_DATAWS_BASE_URL}/re_detail/nearbyGenomic"
        response = await self._post(url, json=payload)
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as exc:
            raise PathwayRegulatoryAPIError(
                f"SCREEN nearby-genes lookup for '{accession}' did not return valid JSON."
            ) from exc
        if isinstance(data, dict) and "errors" in data:
            raise PathwayRegulatoryAPIError(f"SCREEN API returned an error: {data['errors']}")

        nearby_genes = (data or {}).get(accession, {}).get("nearby_genes")
        if nearby_genes is None:
            raise PathwayRegulatoryAPIError(
                f"SCREEN response did not contain 'nearby_genes' data for accession "
                f"'{accession}'."
            )
        sorted_genes = sorted(nearby_genes, key=lambda g: g.get("distance", float("inf")))[:k]
        return {"accession": accession, "genes": sorted_genes}

    # --- query_remap --------------------------------------------------

    async def query_remap(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Queries the real ReMap API for transcription-factor ChIP-seq
        binding peaks intersecting a genomic region.

        Structured arguments:
        - `chrom`, `start`, `end` (required): the genomic region.
        - `release` (optional, default `'2022'`).
        - `assembly` (optional, default `'hg38'`).
        - `datatype` (optional, default `'all'`): one of `REMAP_DATATYPES`
          (`'all'`, `'nr'` non-redundant, `'crm'` cis-regulatory modules).
        - `target` (optional): a transcription-factor name, or a
          `;`-separated list of them, to filter by.
        - `biotype` (optional): a cell-line/biotype name, or a
          `;`-separated list of them, to filter by.
        """
        args = arguments or {}
        chrom = args.get("chrom")
        if not chrom or not str(chrom).strip():
            raise ValueError("query_remap requires a non-empty 'chrom' argument (e.g. 'chr1').")
        start, end = args.get("start"), args.get("end")
        if start is None or end is None:
            raise ValueError(
                "query_remap requires integer 'start' and 'end' genomic coordinate arguments."
            )
        try:
            start_int, end_int = int(start), int(end)
        except (TypeError, ValueError) as exc:
            raise ValueError("query_remap's 'start'/'end' arguments must be integers.") from exc

        release = str(args.get("release", "2022")).strip()
        assembly = str(args.get("assembly", "hg38")).strip()
        datatype = str(args.get("datatype", "all")).strip().lower()
        if datatype not in REMAP_DATATYPES:
            raise ValueError(
                f"query_remap's 'datatype' argument must be one of: {sorted(REMAP_DATATYPES)}."
            )

        region = f"{str(chrom).strip()}:{start_int}-{end_int}"
        path_segments = [REMAP_BASE_URL, "get_peaks", release, assembly, datatype, region]

        target = args.get("target")
        if target and str(target).strip():
            path_segments += ["target", str(target).strip()]
        biotype = args.get("biotype")
        if biotype and str(biotype).strip():
            path_segments += ["biotype", str(biotype).strip()]

        url = "/".join(path_segments)
        response = await self._get(url)
        if response.status_code == 404:
            raise PathwayRegulatoryAPIError(
                f"ReMap query for region '{region}' returned no results (404)."
            )
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as exc:
            raise PathwayRegulatoryAPIError(
                f"ReMap query for region '{region}' did not return valid JSON."
            ) from exc
        if not isinstance(data, dict) or "peaks" not in data:
            raise PathwayRegulatoryAPIError(
                f"ReMap response for region '{region}' did not contain the expected "
                "'peaks' data."
            )
        return data


def register_pathway_regulatory_db_tools(
    registry: MCPServerRegistry, client: Optional[httpx.AsyncClient] = None
) -> List[str]:
    """Registers the pathway/interaction/regulatory-database tool handlers
    into `registry`.

    Returns the registered tool names. Always safe to call -- like
    `register_direct_bio_tools`, these APIs need no configuration/auth, so
    there is no failure mode here worth guarding against at the call site.
    """
    adapters = PathwayRegulatoryDBAdapters(client)
    handlers = {
        "query_kegg": adapters.query_kegg,
        "query_stringdb": adapters.query_stringdb,
        "query_reactome": adapters.query_reactome,
        "query_regulomedb": adapters.query_regulomedb,
        "query_jaspar": adapters.query_jaspar,
        "region_to_ccre_screen": adapters.region_to_ccre_screen,
        "get_genes_near_ccre": adapters.get_genes_near_ccre,
        "query_remap": adapters.query_remap,
    }
    for tool_name, handler in handlers.items():
        registry.register_server(tool_name, handler)
    return list(handlers.keys())
