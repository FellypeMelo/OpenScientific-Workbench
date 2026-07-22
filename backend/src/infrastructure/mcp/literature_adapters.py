"""Literature & search support adapters: real HTTP calls to public
literature/search APIs (Fase 2 DB-adapter catalog, "literature" section).

Covers 7 tools: ``fetch_supplementary_info_from_doi``, ``query_arxiv``,
``query_scholar``, ``query_pubmed``, ``search_google``,
``extract_url_content``, ``extract_pdf_content``.

Structured-args-only limitation
--------------------------------
The original Biomni paper's DB tools accept a free-text natural-language
``query`` and rely on an LLM schema-parsing layer to turn it into a real API
call. OSW has no such NL-to-query layer wired into this adapter tier, so
every tool here takes STRUCTURED arguments (a DOI, a search term, a URL, an
arXiv query string, ...) instead -- never a free-form NL prompt that gets
"interpreted". Callers (an LLM agent upstream of this adapter) are expected
to already have extracted the structured value before calling these tools.

Design deviations from the generic Fase 2 guidance, and why
-------------------------------------------------------------
- HTTP client: the task's extra note for this domain suggested
  ``requests`` for ``extract_url_content``. This module uses ``httpx``
  (already a dependency) instead, for every tool including that one, to
  match ``bio_direct_adapters.py``'s exact convention this module must
  follow: a class wrapping an *injectable* ``httpx.AsyncClient`` so tests
  can use ``httpx.MockTransport`` with zero real network calls. ``requests``
  is synchronous and has no equivalent test-double story in this codebase.
  ``beautifulsoup4`` (genuinely not previously a dependency) is added to
  ``pyproject.toml`` for HTML parsing only -- ``requests`` is not added.
- Settings/credentials: several of these APIs work better (or, for
  ``search_google``, only work at all) with a configured credential --
  ``settings.GOOGLE_SEARCH_API_KEY``/``GOOGLE_SEARCH_ENGINE_ID``,
  ``SEMANTIC_SCHOLAR_API_KEY``, ``CROSSREF_MAILTO``, and (shared with
  ``expression_browser_db_adapters.py``'s ``query_geo``, both being the same
  underlying NCBI Entrez eutils service) ``NCBI_EMAIL``/``NCBI_API_KEY``. All
  five live on the central ``Settings`` class, same convention as
  ``DEEPSEEK_API_KEY``. Nothing is ever hardcoded -- an unset value simply
  means "no credential configured" (each tool degrades or raises a clear
  error, never fakes a key).
- ``query_scholar``: Google Scholar itself has no public API, and scraping
  its results HTML is both fragile and against Google's Terms of Service
  (the same reason ``search_google`` below uses the real Google Custom
  Search JSON API instead of scraping google.com). As the closest real,
  stable, public, unauthenticated-by-default API serving the same "search
  scholarly literature" purpose, this tool calls the Semantic Scholar Graph
  API (``api.semanticscholar.org``) instead. This is a genuine, verifiable
  substitute implementation, not a skipped tool -- see the docstring on
  ``query_scholar`` below. A literal Google Scholar result would require a
  paid third-party scraping API (e.g. SerpApi) and is out of scope without
  such a key being provisioned.
"""
import asyncio
import io
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from src.infrastructure.config import settings
from src.infrastructure.mcp.server_registry import MCPServerRegistry

CROSSREF_WORKS_BASE_URL = "https://api.crossref.org/works"
ARXIV_API_BASE_URL = "http://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
PUBMED_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
GOOGLE_CUSTOM_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"

# Generous but bounded -- these are real, sometimes slow, third-party services.
DEFAULT_TIMEOUT_SECONDS = 30.0

# A descriptive UA is more polite (and less likely to be blocked) than
# httpx's default `python-httpx/x.y` string when hitting arbitrary publisher
# URLs in `extract_url_content`/`extract_pdf_content`.
DEFAULT_USER_AGENT = (
    "OpenScientific-Workbench/1.0 (+https://github.com/OpenScientific-Workbench)"
)

_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

#: MCP tool name -> registered handler, see `register_literature_tools`.
LITERATURE_TOOL_NAMES = (
    "fetch_supplementary_info_from_doi",
    "query_arxiv",
    "query_scholar",
    "query_pubmed",
    "search_google",
    "extract_url_content",
    "extract_pdf_content",
)


class LiteratureAPIError(RuntimeError):
    """Raised when a literature/search REST API call fails: a non-2xx
    response (other than a clean 404, reported as a more specific `not
    found` message), a response body that doesn't have the shape this
    adapter expects, or a required credential is not configured."""


def _text(element: Optional[ElementTree.Element]) -> Optional[str]:
    if element is None or element.text is None:
        return None
    return element.text.strip() or None


class LiteratureAdapters:
    """Thin async wrapper around real public literature/search REST APIs.

    An `httpx.AsyncClient` can be injected (tests use `httpx.MockTransport`,
    mirroring `BioDirectAdapters`'s test pattern); otherwise a fresh client
    is created per call, so callers never have to manage a client lifecycle.
    """

    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._client = client

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

    # --- fetch_supplementary_info_from_doi ---------------------------------

    async def fetch_supplementary_info_from_doi(
        self, arguments: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Fetches a work's metadata (title, resource links, and any
        publisher-registered supplementary/full-text links) from the real
        Crossref REST API, given a structured DOI.

        Crossref does not have a dedicated "supplementary materials"
        endpoint; the ``link`` array in a work's metadata is the closest
        real, stable, publicly documented field publishers use to register
        extra resource URLs (full text, similarity-checking copies, etc.),
        so that array is surfaced as-is here. Coverage is best-effort and
        depends on what the publisher registered with Crossref.
        """
        doi = (arguments or {}).get("doi")
        if not doi or not str(doi).strip():
            raise ValueError(
                "fetch_supplementary_info_from_doi requires a non-empty 'doi' argument "
                "(e.g. '10.1038/s41586-021-03819-2')."
            )
        doi = str(doi).strip()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if doi.lower().startswith(prefix):
                doi = doi[len(prefix):]
                break

        params = {}
        mailto = settings.CROSSREF_MAILTO
        if mailto:
            params["mailto"] = mailto

        url = f"{CROSSREF_WORKS_BASE_URL}/{doi}"
        response = await self._get(url, params=params or None)
        if response.status_code == 404:
            raise LiteratureAPIError(f"DOI '{doi}' was not found in Crossref.")
        response.raise_for_status()

        try:
            data = response.json()
            message = data["message"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LiteratureAPIError(
                f"Crossref response for DOI '{doi}' did not contain the expected work metadata."
            ) from exc

        title_list = message.get("title") or []
        return {
            "doi": doi,
            "title": " ".join(title_list) if title_list else None,
            "container_title": " ".join(message.get("container-title") or []) or None,
            "links": message.get("link", []),
            "resource_url": ((message.get("resource") or {}).get("primary") or {}).get("URL"),
        }

    # --- query_arxiv ---------------------------------------------------------

    async def query_arxiv(self, arguments: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Queries the real arXiv API (Atom XML feed) via a structured
        ``search_query`` (arXiv's own query-string syntax, e.g.
        ``'all:transformer AND cat:cs.LG'``) and/or a structured
        ``id_list`` of arXiv IDs."""
        args = arguments or {}
        search_query = args.get("search_query")
        raw_id_list = args.get("id_list")
        ids = [raw_id_list] if isinstance(raw_id_list, str) else list(raw_id_list or [])
        ids = [str(i).strip() for i in ids if str(i).strip()]
        if (not search_query or not str(search_query).strip()) and not ids:
            raise ValueError(
                "query_arxiv requires a non-empty 'search_query' (arXiv query syntax) and/or "
                "'id_list' argument."
            )

        params: Dict[str, Any] = {}
        if search_query and str(search_query).strip():
            params["search_query"] = str(search_query).strip()
        if ids:
            params["id_list"] = ",".join(ids)
        try:
            params["start"] = int(args.get("start", 0))
            params["max_results"] = int(args.get("max_results", 10))
        except (TypeError, ValueError) as exc:
            raise ValueError("query_arxiv's 'start'/'max_results' arguments must be integers.") from exc

        response = await self._get(ARXIV_API_BASE_URL, params=params)
        response.raise_for_status()

        try:
            root = ElementTree.fromstring(response.text)
        except ElementTree.ParseError as exc:
            raise LiteratureAPIError("arXiv API returned a response that could not be parsed as XML.") from exc

        entries = root.findall("atom:entry", _ATOM_NS)
        results = []
        for entry in entries:
            entry_id = _text(entry.find("atom:id", _ATOM_NS))
            pdf_url = next(
                (
                    link.get("href")
                    for link in entry.findall("atom:link", _ATOM_NS)
                    if link.get("title") == "pdf"
                ),
                None,
            )
            results.append(
                {
                    "id": entry_id,
                    "arxiv_id": entry_id.rsplit("/", 1)[-1] if entry_id else None,
                    "title": _text(entry.find("atom:title", _ATOM_NS)),
                    "summary": _text(entry.find("atom:summary", _ATOM_NS)),
                    "published": _text(entry.find("atom:published", _ATOM_NS)),
                    "authors": [
                        _text(author.find("atom:name", _ATOM_NS))
                        for author in entry.findall("atom:author", _ATOM_NS)
                    ],
                    "pdf_url": pdf_url,
                }
            )
        return results

    # --- query_scholar ---------------------------------------------------------

    async def query_scholar(self, arguments: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Queries scholarly literature via the real Semantic Scholar Graph
        API, given a structured search ``query``.

        Google Scholar itself has no public API; see the module docstring
        for why Semantic Scholar is used here as the real, stable, public
        substitute rather than scraping google.com/scholar HTML.
        """
        args = arguments or {}
        query = args.get("query")
        if not query or not str(query).strip():
            raise ValueError("query_scholar requires a non-empty 'query' argument.")

        params = {
            "query": str(query).strip(),
            "limit": int(args.get("limit", 10)),
            "fields": "title,abstract,year,authors,url,externalIds,venue",
        }
        headers = {}
        api_key = settings.SEMANTIC_SCHOLAR_API_KEY
        if api_key:
            headers["x-api-key"] = api_key

        response = await self._get(SEMANTIC_SCHOLAR_SEARCH_URL, params=params, headers=headers or None)
        if response.status_code == 429:
            raise LiteratureAPIError(
                "Semantic Scholar API rate-limited this request (HTTP 429); consider setting "
                "the SEMANTIC_SCHOLAR_API_KEY environment variable for a higher quota."
            )
        response.raise_for_status()

        try:
            data = response.json()
            papers = data["data"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LiteratureAPIError(
                "Semantic Scholar search response did not contain the expected result shape."
            ) from exc

        results = []
        for paper in papers:
            external_ids = paper.get("externalIds") or {}
            results.append(
                {
                    "title": paper.get("title"),
                    "abstract": paper.get("abstract"),
                    "year": paper.get("year"),
                    "authors": [
                        author.get("name") for author in (paper.get("authors") or []) if isinstance(author, dict)
                    ],
                    "url": paper.get("url"),
                    "doi": external_ids.get("DOI"),
                    "venue": paper.get("venue"),
                }
            )
        return results

    # --- query_pubmed ---------------------------------------------------------

    async def query_pubmed(self, arguments: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Queries the real NCBI PubMed E-utilities API: a structured
        ``term`` search (esearch -> esummary) or a structured ``pmids`` list
        (esummary directly)."""
        args = arguments or {}
        term = args.get("term")
        raw_pmids = args.get("pmids")
        pmids = [raw_pmids] if isinstance(raw_pmids, (str, int)) else list(raw_pmids or [])
        pmids = [str(p).strip() for p in pmids if str(p).strip()]
        if (not term or not str(term).strip()) and not pmids:
            raise ValueError(
                "query_pubmed requires a non-empty 'term' (search query) or 'pmids' (a PMID or "
                "list of PMIDs) argument."
            )

        common_params: Dict[str, Any] = {}
        email = settings.NCBI_EMAIL
        api_key = settings.NCBI_API_KEY
        if email:
            common_params["email"] = email
        if api_key:
            common_params["api_key"] = api_key

        if not pmids:
            search_params = {
                "db": "pubmed",
                "term": str(term).strip(),
                "retmode": "json",
                "retmax": int(args.get("retmax", 20)),
                **common_params,
            }
            search_response = await self._get(PUBMED_ESEARCH_URL, params=search_params)
            search_response.raise_for_status()
            try:
                search_data = search_response.json()
                pmids = search_data["esearchresult"]["idlist"]
            except (ValueError, KeyError, TypeError) as exc:
                raise LiteratureAPIError(
                    "PubMed esearch response did not contain the expected result shape."
                ) from exc
            if not pmids:
                return []

        summary_params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "json", **common_params}
        summary_response = await self._get(PUBMED_ESUMMARY_URL, params=summary_params)
        summary_response.raise_for_status()
        try:
            summary_data = summary_response.json()
            result = summary_data["result"]
            uids = result["uids"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LiteratureAPIError(
                "PubMed esummary response did not contain the expected result shape."
            ) from exc

        articles = []
        for uid in uids:
            entry = result.get(uid) or {}
            article_ids = entry.get("articleids") or []
            doi = next(
                (aid.get("value") for aid in article_ids if isinstance(aid, dict) and aid.get("idtype") == "doi"),
                None,
            )
            articles.append(
                {
                    "pmid": uid,
                    "title": entry.get("title"),
                    "authors": [
                        author.get("name") for author in (entry.get("authors") or []) if isinstance(author, dict)
                    ],
                    "source": entry.get("source"),
                    "pubdate": entry.get("pubdate"),
                    "doi": doi,
                }
            )
        return articles

    # --- search_google ---------------------------------------------------------

    async def search_google(self, arguments: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Searches the web via the real Google Custom Search JSON API,
        given a structured ``query``. Requires the ``GOOGLE_SEARCH_API_KEY``
        and ``GOOGLE_SEARCH_ENGINE_ID`` environment variables to be
        configured -- Google's search results page is deliberately NOT
        scraped (fragile HTML, against Google's Terms of Service)."""
        args = arguments or {}
        query = args.get("query")
        if not query or not str(query).strip():
            raise ValueError("search_google requires a non-empty 'query' argument.")

        api_key = settings.GOOGLE_SEARCH_API_KEY
        engine_id = settings.GOOGLE_SEARCH_ENGINE_ID
        if not api_key or not engine_id:
            raise LiteratureAPIError(
                "search_google requires the GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_ENGINE_ID "
                "settings (Google Custom Search JSON API credentials) to be configured; at "
                "least one is not set."
            )

        params = {
            "key": api_key,
            "cx": engine_id,
            "q": str(query).strip(),
            "num": int(args.get("num", 10)),
        }
        response = await self._get(GOOGLE_CUSTOM_SEARCH_URL, params=params)
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as exc:
            raise LiteratureAPIError("Google Custom Search API returned a non-JSON response.") from exc
        if not isinstance(data, dict):
            raise LiteratureAPIError("Google Custom Search API returned an unexpected response shape.")

        items = data.get("items") or []
        return [
            {"title": item.get("title"), "link": item.get("link"), "snippet": item.get("snippet")}
            for item in items
        ]

    # --- extract_url_content ---------------------------------------------------------

    async def extract_url_content(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Fetches a real URL and extracts its page title + readable text
        (script/style stripped) via BeautifulSoup4."""
        url = (arguments or {}).get("url")
        if not url or not str(url).strip():
            raise ValueError("extract_url_content requires a non-empty 'url' argument.")
        url = str(url).strip()

        response = await self._get(url, headers={"User-Agent": DEFAULT_USER_AGENT})
        if response.status_code == 404:
            raise LiteratureAPIError(f"URL '{url}' returned 404 Not Found.")
        response.raise_for_status()

        html = response.text
        if not html.strip():
            raise LiteratureAPIError(f"Fetching '{url}' returned an empty response body.")

        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as exc:  # pragma: no cover - html.parser is very lenient
            raise LiteratureAPIError(f"Could not parse the content fetched from '{url}' as HTML.") from exc

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        title = soup.title.get_text(strip=True) if soup.title else None
        text = soup.get_text(separator="\n", strip=True)

        return {"url": url, "title": title, "text": text}

    # --- extract_pdf_content ---------------------------------------------------------

    async def extract_pdf_content(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Extracts the text layer of a PDF, reusing the same `pypdf`
        per-page extraction approach as `PypdfDocumentParser`
        (`infrastructure/parsing/pypdf_adapter.py`). The PDF is either
        downloaded from a structured ``url`` or supplied inline as
        structured base64 bytes via ``pdf_base64``."""
        args = arguments or {}
        url = args.get("url")
        pdf_base64 = args.get("pdf_base64")
        if (not url or not str(url).strip()) and (not pdf_base64 or not str(pdf_base64).strip()):
            raise ValueError(
                "extract_pdf_content requires a non-empty 'url' (to download a PDF) or "
                "'pdf_base64' (inline base64-encoded PDF bytes) argument."
            )

        source: str
        if pdf_base64:
            import base64
            import binascii

            try:
                pdf_bytes = base64.b64decode(str(pdf_base64), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("extract_pdf_content's 'pdf_base64' argument is not valid base64.") from exc
            source = "inline"
        else:
            url = str(url).strip()
            response = await self._get(url)
            if response.status_code == 404:
                raise LiteratureAPIError(f"PDF at '{url}' was not found.")
            response.raise_for_status()
            pdf_bytes = response.content
            if not pdf_bytes:
                raise LiteratureAPIError(f"Fetching PDF at '{url}' returned an empty response body.")
            source = url

        text = await asyncio.to_thread(self._parse_pdf_sync, pdf_bytes)
        if not text.strip():
            raise LiteratureAPIError(
                "No extractable text layer was found in the PDF (it may be a scanned/image-only "
                "PDF with no embedded text)."
            )
        return {"source": source, "text": text, "length": len(text)}

    @staticmethod
    def _parse_pdf_sync(pdf_bytes: bytes) -> str:
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            pages_text = []
            for page in reader.pages:
                text = (page.extract_text() or "").strip()
                if text:
                    pages_text.append(text)
        except Exception as exc:
            raise LiteratureAPIError("The fetched/provided content is not a valid, readable PDF file.") from exc
        return "\n\n".join(pages_text)


def register_literature_tools(
    registry: MCPServerRegistry, client: Optional[httpx.AsyncClient] = None
) -> List[str]:
    """Registers the literature/search tool handlers into `registry`.

    Returns the registered tool names. Always safe to call -- registration
    itself needs no configuration; individual tools that do need a
    credential (`search_google`) raise `LiteratureAPIError` at call time if
    it is missing, rather than failing registration.
    """
    adapters = LiteratureAdapters(client)
    handlers = {
        "fetch_supplementary_info_from_doi": adapters.fetch_supplementary_info_from_doi,
        "query_arxiv": adapters.query_arxiv,
        "query_scholar": adapters.query_scholar,
        "query_pubmed": adapters.query_pubmed,
        "search_google": adapters.search_google,
        "extract_url_content": adapters.extract_url_content,
        "extract_pdf_content": adapters.extract_pdf_content,
    }
    for tool_name, handler in handlers.items():
        registry.register_server(tool_name, handler)
    return list(handlers.keys())
