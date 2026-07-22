"""Direct variant/clinical-genomics DB adapters calling real public REST/GraphQL
APIs -- ClinVar, dbSNP, gnomAD, the GWAS Catalog, OpenTargets (Platform +
Genetics), and cBioPortal.

Same pattern as ``bio_direct_adapters.py`` (``BioDirectAdapters``): a thin
class wrapping an optionally-injected ``httpx.AsyncClient``, one async method
per tool, a domain-specific ``RuntimeError`` subclass raised on a bad/
unexpected response shape, and a module-level
``register_variant_clinical_db_tools(registry, client=None) -> List[str]``.

STRUCTURED ARGS ONLY: the original Biomni-style catalog entries for these
tools describe a "natural-language OR direct-endpoint" interface (an LLM
parses a free-text prompt into a structured query). OSW has no NL-to-query
LLM layer wired into this adapter tier, so every tool below requires
structured arguments instead -- an accession/rsID/gene symbol/Ensembl ID/
study ID, as appropriate per tool (documented on each method). Passing a
free-text "query" string is not supported and will not be silently
interpreted.

Endpoints used (each verified against the live public API while writing this
module, not guessed from memory of possibly-stale documentation):

- ClinVar (``query_clinvar``): NCBI E-utilities ``esearch.fcgi``/
  ``esummary.fcgi`` against ``db=clinvar``
  (https://eutils.ncbi.nlm.nih.gov/entrez/eutils/).
- dbSNP (``query_dbsnp``): NCBI E-utilities ``esummary.fcgi`` against
  ``db=snp``.
- gnomAD (``query_gnomad``): the public gnomAD GraphQL API
  (https://gnomad.broadinstitute.org/api).
- GWAS Catalog (``query_gwas_catalog``): the EBI GWAS Catalog REST API
  (https://www.ebi.ac.uk/gwas/rest/api), a HAL/JSON API.
- OpenTargets Platform (``query_opentarget``) and OpenTargets Genetics
  (``query_opentarget_genetics``): both hit
  ``https://api.platform.opentargets.org/api/v4/graphql``. As of this
  writing, the standalone "OpenTargets Genetics" service
  (genetics.opentargets.org) has been merged into the main OpenTargets
  Platform and now 301-redirects there -- confirmed live, not assumed --
  so ``query_opentarget_genetics`` is a variant/locus-centric GraphQL query
  (fine-mapped GWAS credible sets) against that same endpoint, distinct from
  ``query_opentarget``'s target-disease-association query.
- cBioPortal (``query_cbioportal``): the public cBioPortal REST API
  (https://www.cbioportal.org/api).

Contact email / API key: several NCBI E-utilities endpoints (ClinVar, dbSNP)
work better (higher, documented rate limits) with an ``email``/``api_key``
query param, and this task's Settings-field guidance suggests wiring one up.
That change belongs in ``src/infrastructure/config.py``, which is out of
scope for this module per this task's file boundaries (only this adapter
file and its test file). These two tools therefore currently call NCBI
unauthenticated -- a real, documented gap, not a secret one; a future pass
that *does* own ``config.py`` should add an ``Optional[str] = None``
``NCBI_ENTREZ_EMAIL`` (and optionally ``NCBI_API_KEY``) setting following the
``DEEPSEEK_API_KEY`` convention there and thread it through as an extra
query param on the ``NCBI_ESUMMARY_URL``/``CLINVAR_ESEARCH_URL`` calls below.

Retry/backoff: no shared retry helper exists anywhere else in this codebase
yet (a real, confirmed gap -- see ``docs/tools/db_adapter_catalog.md``). This
module adds a small, local, hand-rolled bounded-retry wrapper (``_send``)
used by every HTTP call this file makes, rather than a new cross-file shared
module or a new ``tenacity`` dependency -- this task's hard rules restrict
edits to this adapter file and its test file only, so a shared module living
elsewhere is not an option here. It retries only on transport-level errors
and 429/5xx responses (never on 404s or other 4xxs, which are meaningful,
final answers from these APIs), a small fixed number of times with a short
exponential backoff.
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from src.infrastructure.mcp.server_registry import MCPServerRegistry

logger = logging.getLogger(__name__)

NCBI_EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CLINVAR_ESEARCH_URL = f"{NCBI_EUTILS_BASE_URL}/esearch.fcgi"
# esummary.fcgi is shared by ClinVar (db=clinvar) and dbSNP (db=snp) -- only
# the `db` query param differs between the two tools that use this.
NCBI_ESUMMARY_URL = f"{NCBI_EUTILS_BASE_URL}/esummary.fcgi"

GNOMAD_GRAPHQL_URL = "https://gnomad.broadinstitute.org/api"
GWAS_CATALOG_BASE_URL = "https://www.ebi.ac.uk/gwas/rest/api"
OPENTARGETS_GRAPHQL_URL = "https://api.platform.opentargets.org/api/v4/graphql"
CBIOPORTAL_BASE_URL = "https://www.cbioportal.org/api"

# Generous but bounded -- these are real, sometimes slow, third-party services
# (same convention as `bio_direct_adapters.py`).
DEFAULT_TIMEOUT_SECONDS = 30.0

# --- Local retry/backoff (see module docstring) -----------------------------
MAX_ATTEMPTS = 3
RETRY_BACKOFF_BASE_SECONDS = 0.05
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

#: MCP tool name -> handled by this module's `VariantClinicalAdapters`.
VARIANT_CLINICAL_TOOL_NAMES = (
    "query_clinvar",
    "query_dbsnp",
    "query_gnomad",
    "query_gwas_catalog",
    "query_opentarget_genetics",
    "query_opentarget",
    "query_cbioportal",
)


class VariantClinicalAPIError(RuntimeError):
    """Raised when a variant/clinical-genomics DB API call fails: a non-2xx
    response (other than a clean 404, which is reported as a more specific
    `not found` message) or a response body that doesn't have the shape this
    adapter expects (including a GraphQL 200 response carrying an `errors`
    payload instead of `data`)."""


def _positive_int(value: Any, *, default: int, field_name: str) -> int:
    """Coerces an optional argument to a positive `int`, raising a clear
    `ValueError` (not a bare `TypeError`/`ValueError` from `int()`) on a bad
    value -- used for every tool's optional `max_results`-style argument."""
    if value is None:
        return default
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"'{field_name}' must be an integer, got {value!r}.") from None
    if n <= 0:
        raise ValueError(f"'{field_name}' must be a positive integer, got {n}.")
    return n


class VariantClinicalAdapters:
    """Thin async wrapper around the real ClinVar/dbSNP/gnomAD/GWAS Catalog/
    OpenTargets/cBioPortal public APIs.

    An `httpx.AsyncClient` can be injected (tests use `httpx.MockTransport`,
    mirroring `BioDirectAdapters`'s test pattern); otherwise a fresh client is
    created per underlying HTTP call, so callers never have to manage a
    client lifecycle.
    """

    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._client = client

    async def _send(self, do_request) -> httpx.Response:
        """Executes `do_request(client)`, retrying a bounded number of times
        on transport errors and 429/5xx responses only. 404s and other 4xxs
        are returned immediately as final answers -- see module docstring."""
        owns_client = self._client is None
        client = self._client if not owns_client else httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS)
        try:
            last_response: Optional[httpx.Response] = None
            last_exc: Optional[Exception] = None
            for attempt in range(MAX_ATTEMPTS):
                try:
                    response = await do_request(client)
                except httpx.TransportError as exc:
                    last_exc = exc
                    last_response = None
                else:
                    if response.status_code not in RETRYABLE_STATUS_CODES:
                        return response
                    last_response = response
                    last_exc = None
                if attempt < MAX_ATTEMPTS - 1:
                    await asyncio.sleep(RETRY_BACKOFF_BASE_SECONDS * (2**attempt))
            if last_response is not None:
                return last_response
            assert last_exc is not None  # one of the two branches above always sets it
            raise last_exc
        finally:
            if owns_client:
                await client.aclose()

    async def _get(self, url: str, *, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
        return await self._send(lambda client: client.get(url, params=params))

    async def _post_graphql(
        self, url: str, query: str, variables: Dict[str, Any]
    ) -> Dict[str, Any]:
        """POSTs a GraphQL query and returns its `data` payload, raising
        `VariantClinicalAPIError` on a non-JSON body, a GraphQL `errors`
        payload, or a missing/`null` `data` field."""
        response = await self._send(
            lambda client: client.post(url, json={"query": query, "variables": variables})
        )
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as exc:
            raise VariantClinicalAPIError(f"{url} returned a non-JSON response.") from exc
        if not isinstance(body, dict):
            raise VariantClinicalAPIError(f"{url} returned an unexpected response shape.")
        errors = body.get("errors")
        if errors:
            messages = "; ".join(
                str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errors
            )
            raise VariantClinicalAPIError(f"{url} returned GraphQL errors: {messages}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise VariantClinicalAPIError(f"{url} returned no 'data' payload.")
        return data

    # --- query_clinvar ----------------------------------------------------

    async def query_clinvar(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Looks up ClinVar variant records via NCBI E-utilities (esearch +
        esummary against `db=clinvar`).

        Structured args only (see module docstring): at least one of `gene`
        (gene symbol, e.g. `'BRCA1'`) or `variation_id` (a ClinVar numeric
        Variation ID/uid, e.g. `'17661'`, or a zero-padded `'VCV...'`
        accession, e.g. `'VCV000017661'`) is required. When `gene` is given
        without `variation_id`, an optional `clinical_significance` filter
        (e.g. `'pathogenic'`) narrows the Entrez search, and `max_results`
        (default 20) bounds how many matching variants are summarized.
        """
        args = arguments or {}
        gene = args.get("gene")
        variation_id = args.get("variation_id")
        gene = str(gene).strip() if gene and str(gene).strip() else None
        variation_id = str(variation_id).strip() if variation_id and str(variation_id).strip() else None
        if not gene and not variation_id:
            raise ValueError(
                "query_clinvar requires a non-empty 'gene' (e.g. 'BRCA1') or "
                "'variation_id' (e.g. '17661' or 'VCV000017661') argument."
            )
        max_results = _positive_int(args.get("max_results"), default=20, field_name="max_results")

        if variation_id:
            numeric_id = variation_id
            if numeric_id.upper().startswith("VCV"):
                numeric_id = numeric_id[3:].lstrip("0") or "0"
            ids = [numeric_id]
            query_desc: Dict[str, Any] = {"variation_id": variation_id}
        else:
            assert gene is not None
            term = f"{gene}[gene]"
            if args.get("clinical_significance"):
                term += f" AND {str(args['clinical_significance']).strip()}[Clinical_significance]"
            search_response = await self._get(
                CLINVAR_ESEARCH_URL,
                params={"db": "clinvar", "term": term, "retmode": "json", "retmax": max_results},
            )
            search_response.raise_for_status()
            try:
                search_data = search_response.json()
                ids = search_data["esearchresult"]["idlist"]
            except (ValueError, KeyError, TypeError) as exc:
                raise VariantClinicalAPIError(
                    f"ClinVar esearch response for gene '{gene}' did not contain the expected "
                    "result list."
                ) from exc
            query_desc = {"gene": gene, "term": term}
            if not ids:
                return {"query": query_desc, "total_count": 0, "variants": []}

        summary_response = await self._get(
            NCBI_ESUMMARY_URL, params={"db": "clinvar", "id": ",".join(ids), "retmode": "json"}
        )
        summary_response.raise_for_status()
        try:
            summary_data = summary_response.json()
            result = summary_data["result"]
        except (ValueError, KeyError, TypeError) as exc:
            raise VariantClinicalAPIError(
                "ClinVar esummary response did not contain the expected 'result' data."
            ) from exc

        uids = result.get("uids", ids)
        variants: List[Dict[str, Any]] = []
        for uid in uids:
            entry = result.get(uid)
            if not isinstance(entry, dict):
                continue
            # ClinVar renamed `clinical_significance` -> `germline_classification`
            # in its esummary schema; accept either (verified live -- current
            # responses use `germline_classification`).
            classification = entry.get("germline_classification") or entry.get("clinical_significance") or {}
            if not isinstance(classification, dict):
                classification = {"description": classification}
            variants.append(
                {
                    "uid": uid,
                    "accession": entry.get("accession"),
                    "title": entry.get("title"),
                    "object_type": entry.get("obj_type"),
                    "gene": entry.get("gene_sort"),
                    "clinical_significance": classification.get("description"),
                    "review_status": classification.get("review_status"),
                }
            )
        if variation_id and not variants:
            raise VariantClinicalAPIError(f"ClinVar variation '{variation_id}' was not found.")
        return {"query": query_desc, "total_count": len(variants), "variants": variants}

    # --- query_dbsnp --------------------------------------------------------

    async def query_dbsnp(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Looks up an NCBI dbSNP record via E-utilities esummary
        (`db=snp`).

        Structured args only: requires a non-empty `rsid` (e.g.
        `'rs1042522'`; a bare numeric ID like `'1042522'` is also accepted).
        """
        args = arguments or {}
        rsid = args.get("rsid")
        if not rsid or not str(rsid).strip():
            raise ValueError(
                "query_dbsnp requires a non-empty 'rsid' argument (e.g. 'rs1042522' or '1042522')."
            )
        rsid = str(rsid).strip()
        numeric_id = rsid[2:] if rsid.lower().startswith("rs") else rsid
        if not numeric_id.isdigit():
            raise ValueError(f"query_dbsnp requires a numeric rsID (e.g. 'rs1042522'); got '{rsid}'.")

        response = await self._get(NCBI_ESUMMARY_URL, params={"db": "snp", "id": numeric_id, "retmode": "json"})
        response.raise_for_status()
        try:
            data = response.json()
            result = data["result"]
            entry = result[numeric_id]
        except (ValueError, KeyError, TypeError) as exc:
            raise VariantClinicalAPIError(
                f"dbSNP response for rsid 'rs{numeric_id}' did not contain the expected summary data."
            ) from exc
        # A nonexistent uid still comes back 200 OK with `{"error": "..."}`
        # in place of the real fields (verified live) -- not a real record.
        if not isinstance(entry, dict) or entry.get("error"):
            raise VariantClinicalAPIError(f"dbSNP rsID 'rs{numeric_id}' was not found.")

        genes = entry.get("genes") or []
        return {
            "rsid": f"rs{numeric_id}",
            "chromosome": entry.get("chr"),
            "spdi": entry.get("spdi"),
            "function_class": entry.get("fxn_class"),
            "clinical_significance": entry.get("clinical_significance") or None,
            "genes": [g.get("name") for g in genes if isinstance(g, dict) and g.get("name")],
            "global_mafs": entry.get("global_mafs"),
        }

    # --- query_gnomad --------------------------------------------------------

    async def query_gnomad(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Fetches gnomAD population-frequency variants for a gene via the
        real gnomAD GraphQL API.

        Structured args only: requires a non-empty `gene_symbol` (e.g.
        `'PCSK9'`). Optional `dataset_id` (default `'gnomad_r4'`, gnomAD's
        own dataset-selector enum value) and `reference_genome` (`'GRCh37'`
        or `'GRCh38'`, default `'GRCh38'`) narrow the query; `max_results`
        (default 50) bounds how many variants are returned.
        """
        args = arguments or {}
        gene_symbol = args.get("gene_symbol")
        if not gene_symbol or not str(gene_symbol).strip():
            raise ValueError("query_gnomad requires a non-empty 'gene_symbol' argument (e.g. 'PCSK9').")
        gene_symbol = str(gene_symbol).strip()
        dataset_id = str(args.get("dataset_id") or "gnomad_r4").strip()
        reference_genome = str(args.get("reference_genome") or "GRCh38").strip()
        if reference_genome not in ("GRCh37", "GRCh38"):
            raise ValueError("query_gnomad 'reference_genome' must be 'GRCh37' or 'GRCh38'.")
        max_results = _positive_int(args.get("max_results"), default=50, field_name="max_results")

        # `reference_genome` is a GraphQL enum (not a string variable) on
        # gnomAD's schema -- interpolated directly into the query text rather
        # than passed as a `$variable` for that reason. Safe here: the value
        # is validated against a two-item allowlist immediately above, so
        # nothing caller-controlled beyond `"GRCh37"`/`"GRCh38"` ever reaches
        # the query string.
        query = f"""
        query GnomadGeneVariants($geneSymbol: String!, $datasetId: DatasetId!) {{
          gene(gene_symbol: $geneSymbol, reference_genome: {reference_genome}) {{
            gene_id
            symbol
            variants(dataset: $datasetId) {{
              variant_id
              pos
              consequence
              hgvsc
              hgvsp
              rsids
              exome {{ ac an af }}
              genome {{ ac an af }}
            }}
          }}
        }}
        """
        data = await self._post_graphql(
            GNOMAD_GRAPHQL_URL, query, {"geneSymbol": gene_symbol, "datasetId": dataset_id}
        )
        gene = data.get("gene")
        if not isinstance(gene, dict):
            raise VariantClinicalAPIError(f"gnomAD returned no gene data for symbol '{gene_symbol}'.")
        variants = gene.get("variants") or []
        return {
            "gene_symbol": gene.get("symbol", gene_symbol),
            "gene_id": gene.get("gene_id"),
            "dataset_id": dataset_id,
            "total_variants": len(variants),
            "variants": variants[:max_results],
        }

    # --- query_gwas_catalog --------------------------------------------------

    async def query_gwas_catalog(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Queries the EBI GWAS Catalog REST API.

        Structured args only: requires either `rsid` (e.g. `'rs7329174'`,
        returns that SNP's reported associations) or `disease_trait` (e.g.
        `'asthma'`, returns studies matching that reported trait). Optional
        `max_results` (default 20) bounds how many results are returned.
        """
        args = arguments or {}
        rsid = args.get("rsid")
        disease_trait = args.get("disease_trait")
        rsid = str(rsid).strip() if rsid and str(rsid).strip() else None
        disease_trait = str(disease_trait).strip() if disease_trait and str(disease_trait).strip() else None
        if not rsid and not disease_trait:
            raise ValueError(
                "query_gwas_catalog requires a non-empty 'rsid' (e.g. 'rs7329174') or "
                "'disease_trait' (e.g. 'asthma') argument."
            )
        max_results = _positive_int(args.get("max_results"), default=20, field_name="max_results")

        if rsid:
            if not rsid.lower().startswith("rs"):
                rsid = f"rs{rsid}"
            response = await self._get(f"{GWAS_CATALOG_BASE_URL}/singleNucleotidePolymorphisms/{rsid}/associations")
            if response.status_code == 404:
                raise VariantClinicalAPIError(f"GWAS Catalog has no record of SNP '{rsid}'.")
            response.raise_for_status()
            try:
                data = response.json()
            except ValueError as exc:
                raise VariantClinicalAPIError("GWAS Catalog returned a non-JSON response.") from exc
            if not isinstance(data, dict):
                raise VariantClinicalAPIError("GWAS Catalog returned an unexpected response shape.")
            associations = ((data.get("_embedded") or {}).get("associations")) or []
            simplified = []
            for assoc in associations[:max_results]:
                risk_alleles: List[str] = []
                reported_genes: List[str] = []
                for locus in assoc.get("loci") or []:
                    for allele in locus.get("strongestRiskAlleles") or []:
                        name = allele.get("riskAlleleName")
                        if name:
                            risk_alleles.append(name)
                    for gene in locus.get("authorReportedGenes") or []:
                        name = gene.get("geneName")
                        if name:
                            reported_genes.append(name)
                simplified.append(
                    {
                        "pvalue": assoc.get("pvalue"),
                        "or_per_copy_num": assoc.get("orPerCopyNum"),
                        "risk_frequency": assoc.get("riskFrequency"),
                        "risk_alleles": risk_alleles,
                        "reported_genes": reported_genes,
                        "study_href": ((assoc.get("_links") or {}).get("study") or {}).get("href"),
                    }
                )
            return {"rsid": rsid, "total_associations": len(associations), "associations": simplified}

        response = await self._get(
            f"{GWAS_CATALOG_BASE_URL}/studies/search/findByDiseaseTrait",
            params={"diseaseTrait": disease_trait, "size": max_results},
        )
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError as exc:
            raise VariantClinicalAPIError("GWAS Catalog returned a non-JSON response.") from exc
        if not isinstance(data, dict):
            raise VariantClinicalAPIError("GWAS Catalog returned an unexpected response shape.")
        studies = ((data.get("_embedded") or {}).get("studies")) or []
        simplified_studies = [
            {
                "accession_id": s.get("accessionId"),
                "disease_trait": (s.get("diseaseTrait") or {}).get("trait"),
                "initial_sample_size": s.get("initialSampleSize"),
                "publication": (s.get("publicationInfo") or {}).get("publication"),
                "pubmed_id": (s.get("publicationInfo") or {}).get("pubmedId"),
                "title": (s.get("publicationInfo") or {}).get("title"),
            }
            for s in studies[:max_results]
        ]
        return {"disease_trait": disease_trait, "total_studies": len(studies), "studies": simplified_studies}

    # --- query_opentarget -----------------------------------------------------

    async def query_opentarget(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Fetches target-disease association scores from the real
        OpenTargets Platform GraphQL API.

        Structured args only: requires either `ensembl_id` (e.g.
        `'ENSG00000012048'`) or `gene_symbol` (e.g. `'BRCA1'`, resolved to an
        Ensembl target ID via OpenTargets' own search endpoint first).
        Optional `max_results` (default 15) bounds how many associated
        diseases are returned.
        """
        args = arguments or {}
        ensembl_id = args.get("ensembl_id")
        gene_symbol = args.get("gene_symbol")
        ensembl_id = str(ensembl_id).strip() if ensembl_id and str(ensembl_id).strip() else None
        gene_symbol = str(gene_symbol).strip() if gene_symbol and str(gene_symbol).strip() else None
        if not ensembl_id and not gene_symbol:
            raise ValueError(
                "query_opentarget requires a non-empty 'ensembl_id' (e.g. 'ENSG00000012048') or "
                "'gene_symbol' (e.g. 'BRCA1') argument."
            )
        max_results = _positive_int(args.get("max_results"), default=15, field_name="max_results")

        if not ensembl_id:
            search_query = """
            query SearchTarget($q: String!) {
              search(queryString: $q, entityNames: ["target"]) {
                hits { id entity name }
              }
            }
            """
            search_data = await self._post_graphql(OPENTARGETS_GRAPHQL_URL, search_query, {"q": gene_symbol})
            hits = ((search_data.get("search") or {}).get("hits")) or []
            target_hit = next((h for h in hits if h.get("entity") == "target"), None)
            if not target_hit or not target_hit.get("id"):
                raise VariantClinicalAPIError(
                    f"OpenTargets found no target matching gene symbol '{gene_symbol}'."
                )
            ensembl_id = target_hit["id"]

        target_query = """
        query TargetDiseases($id: String!) {
          target(ensemblId: $id) {
            id
            approvedSymbol
            associatedDiseases {
              count
              rows { score disease { id name } }
            }
          }
        }
        """
        data = await self._post_graphql(OPENTARGETS_GRAPHQL_URL, target_query, {"id": ensembl_id})
        target = data.get("target")
        if not isinstance(target, dict):
            raise VariantClinicalAPIError(f"OpenTargets has no target record for Ensembl ID '{ensembl_id}'.")
        associated = target.get("associatedDiseases") or {}
        rows = associated.get("rows") or []
        return {
            "ensembl_id": target.get("id", ensembl_id),
            "approved_symbol": target.get("approvedSymbol"),
            "total_associations": associated.get("count", len(rows)),
            "associations": [
                {
                    "disease_id": (r.get("disease") or {}).get("id"),
                    "disease_name": (r.get("disease") or {}).get("name"),
                    "score": r.get("score"),
                }
                for r in rows[:max_results]
            ],
        }

    # --- query_opentarget_genetics ---------------------------------------------

    async def query_opentarget_genetics(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Fetches fine-mapped GWAS credible-set (locus-to-trait) data for a
        variant from the OpenTargets Platform GraphQL API.

        NOTE: the standalone "OpenTargets Genetics" service
        (genetics.opentargets.org) has been merged into the main OpenTargets
        Platform and now redirects there (confirmed live) -- this tool hits
        the same `api.platform.opentargets.org` GraphQL endpoint as
        `query_opentarget`, just a variant/locus-centric query rather than a
        target-disease one.

        Structured args only: requires either `variant_id` in OpenTargets'
        own GRCh38 `chr_pos_ref_alt` form (e.g. `'1_154453788_C_T'`) or
        `rsid` (e.g. `'rs4129267'`, resolved to a variant ID via OpenTargets'
        own search endpoint first). Optional `max_results` (default 25)
        bounds how many credible sets are returned.
        """
        args = arguments or {}
        variant_id = args.get("variant_id")
        rsid = args.get("rsid")
        variant_id = str(variant_id).strip() if variant_id and str(variant_id).strip() else None
        rsid = str(rsid).strip() if rsid and str(rsid).strip() else None
        if not variant_id and not rsid:
            raise ValueError(
                "query_opentarget_genetics requires a non-empty 'variant_id' "
                "(e.g. '1_154453788_C_T', GRCh38 chr_pos_ref_alt) or 'rsid' "
                "(e.g. 'rs4129267') argument."
            )
        max_results = _positive_int(args.get("max_results"), default=25, field_name="max_results")

        if not variant_id:
            search_query = """
            query SearchVariant($q: String!) {
              search(queryString: $q, entityNames: ["variant"]) {
                hits { id entity name }
              }
            }
            """
            search_data = await self._post_graphql(OPENTARGETS_GRAPHQL_URL, search_query, {"q": rsid})
            hits = ((search_data.get("search") or {}).get("hits")) or []
            variant_hit = next((h for h in hits if h.get("entity") == "variant"), None)
            if not variant_hit or not variant_hit.get("id"):
                raise VariantClinicalAPIError(f"OpenTargets found no variant matching rsID '{rsid}'.")
            variant_id = variant_hit["id"]

        variant_query = """
        query VariantCredibleSets($id: String!) {
          variant(variantId: $id) {
            id
            rsIds
            chromosome
            position
            referenceAllele
            alternateAllele
            mostSevereConsequence { label }
            credibleSets {
              count
              rows { studyLocusId study { id traitFromSource } }
            }
          }
        }
        """
        data = await self._post_graphql(OPENTARGETS_GRAPHQL_URL, variant_query, {"id": variant_id})
        variant = data.get("variant")
        if not isinstance(variant, dict):
            raise VariantClinicalAPIError(f"OpenTargets has no variant record for '{variant_id}'.")
        credible_sets = variant.get("credibleSets") or {}
        rows = credible_sets.get("rows") or []
        return {
            "variant_id": variant.get("id", variant_id),
            "rsids": variant.get("rsIds") or [],
            "chromosome": variant.get("chromosome"),
            "position": variant.get("position"),
            "reference_allele": variant.get("referenceAllele"),
            "alternate_allele": variant.get("alternateAllele"),
            "most_severe_consequence": (variant.get("mostSevereConsequence") or {}).get("label"),
            "total_credible_sets": credible_sets.get("count", len(rows)),
            "credible_sets": [
                {
                    "study_locus_id": r.get("studyLocusId"),
                    "study_id": (r.get("study") or {}).get("id"),
                    "trait": (r.get("study") or {}).get("traitFromSource"),
                }
                for r in rows[:max_results]
            ],
        }

    # --- query_cbioportal -----------------------------------------------------

    async def query_cbioportal(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Queries the real cBioPortal REST API for cancer genomics data.

        Structured args only: requires a non-empty `study_id` (e.g.
        `'msk_impact_2017'`; cBioPortal's REST API is study-scoped, so there
        is no "search across every study" endpoint to fall back to here).
        With `study_id` alone, returns that study's metadata. Adding `gene`
        (a Hugo gene symbol, e.g. `'TP53'`) instead fetches mutation calls
        for that gene within the study, from the molecular profile
        `'{study_id}_mutations'` and sample list `'{study_id}_all'` by
        default (both cBioPortal's own standard per-study naming convention
        -- override with `molecular_profile_id`/`sample_list_id` for studies
        that don't follow it). Optional `max_results` (default 50) bounds
        how many mutation records are returned.
        """
        args = arguments or {}
        study_id = args.get("study_id")
        if not study_id or not str(study_id).strip():
            raise ValueError(
                "query_cbioportal requires a non-empty 'study_id' (e.g. 'msk_impact_2017'); "
                "optionally add 'gene' (a Hugo gene symbol, e.g. 'TP53') to fetch mutations for "
                "that gene within the study instead of the study's metadata."
            )
        study_id = str(study_id).strip()
        gene = args.get("gene")
        gene = str(gene).strip() if gene and str(gene).strip() else None
        max_results = _positive_int(args.get("max_results"), default=50, field_name="max_results")

        if not gene:
            response = await self._get(f"{CBIOPORTAL_BASE_URL}/studies/{study_id}")
            if response.status_code == 404:
                raise VariantClinicalAPIError(f"cBioPortal study '{study_id}' was not found.")
            response.raise_for_status()
            try:
                study = response.json()
            except ValueError as exc:
                raise VariantClinicalAPIError(
                    f"cBioPortal returned a non-JSON response for study '{study_id}'."
                ) from exc
            if not isinstance(study, dict):
                raise VariantClinicalAPIError(
                    f"cBioPortal returned an unexpected response shape for study '{study_id}'."
                )
            return {"study_id": study_id, "study": study}

        gene_response = await self._get(f"{CBIOPORTAL_BASE_URL}/genes/{gene}")
        if gene_response.status_code == 404:
            raise VariantClinicalAPIError(f"cBioPortal has no gene record for '{gene}'.")
        gene_response.raise_for_status()
        try:
            gene_data = gene_response.json()
            entrez_gene_id = gene_data["entrezGeneId"]
        except (ValueError, KeyError, TypeError) as exc:
            raise VariantClinicalAPIError(
                f"cBioPortal gene lookup for '{gene}' did not return the expected data."
            ) from exc

        molecular_profile_id = str(args.get("molecular_profile_id") or f"{study_id}_mutations")
        sample_list_id = str(args.get("sample_list_id") or f"{study_id}_all")
        mutations_response = await self._get(
            f"{CBIOPORTAL_BASE_URL}/molecular-profiles/{molecular_profile_id}/mutations",
            params={"sampleListId": sample_list_id, "entrezGeneId": entrez_gene_id, "projection": "SUMMARY"},
        )
        if mutations_response.status_code == 404:
            raise VariantClinicalAPIError(
                f"cBioPortal molecular profile '{molecular_profile_id}' or sample list "
                f"'{sample_list_id}' was not found for study '{study_id}'."
            )
        mutations_response.raise_for_status()
        try:
            mutations = mutations_response.json()
        except ValueError as exc:
            raise VariantClinicalAPIError("cBioPortal returned a non-JSON mutations response.") from exc
        if not isinstance(mutations, list):
            raise VariantClinicalAPIError(
                "cBioPortal returned an unexpected mutations response shape (expected a list)."
            )

        return {
            "study_id": study_id,
            "gene": gene,
            "entrez_gene_id": entrez_gene_id,
            "molecular_profile_id": molecular_profile_id,
            "sample_list_id": sample_list_id,
            "total_mutations": len(mutations),
            "mutations": mutations[:max_results],
        }


def register_variant_clinical_db_tools(
    registry: MCPServerRegistry, client: Optional[httpx.AsyncClient] = None
) -> List[str]:
    """Registers the variant/clinical-genomics DB tool handlers into
    `registry`.

    Returns the registered tool names. Always safe to call -- these public
    APIs need no configuration/auth to reach at all (see module docstring re:
    NCBI email/API key being a real but separately-scoped follow-up), so
    (unlike e.g. `register_skills`) there is no failure mode here worth
    guarding against at the call site.
    """
    adapters = VariantClinicalAdapters(client)
    handlers = {
        "query_clinvar": adapters.query_clinvar,
        "query_dbsnp": adapters.query_dbsnp,
        "query_gnomad": adapters.query_gnomad,
        "query_gwas_catalog": adapters.query_gwas_catalog,
        "query_opentarget_genetics": adapters.query_opentarget_genetics,
        "query_opentarget": adapters.query_opentarget,
        "query_cbioportal": adapters.query_cbioportal,
    }
    for tool_name, handler in handlers.items():
        registry.register_server(tool_name, handler)
    return list(handlers.keys())
