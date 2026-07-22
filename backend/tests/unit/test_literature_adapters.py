"""Literature & search support adapters, tested against httpx's built-in
`MockTransport` (same pattern `test_bio_direct_adapters.py` uses) so no real
network call/external mock server is needed while still exercising the real
HTTP request/response handling logic."""
import base64

import httpx
import pytest

from src.infrastructure.mcp import literature_adapters as literature_adapters_module
from src.infrastructure.mcp.literature_adapters import (
    LiteratureAdapters,
    LiteratureAPIError,
    register_literature_tools,
)
from src.infrastructure.mcp.server_registry import MCPServerRegistry


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- fetch_supplementary_info_from_doi -------------------------------------


@pytest.mark.asyncio
async def test_fetch_supplementary_info_from_doi_success():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "message": {
                    "title": ["A Great Paper"],
                    "container-title": ["Journal of Things"],
                    "link": [{"URL": "https://example.com/supp.pdf", "intended-application": "text-mining"}],
                    "resource": {"primary": {"URL": "https://example.com/paper"}},
                }
            },
        )

    client = _client(handler)
    adapters = LiteratureAdapters(client)

    result = await adapters.fetch_supplementary_info_from_doi({"doi": "10.1038/xyz"})

    assert result["doi"] == "10.1038/xyz"
    assert result["title"] == "A Great Paper"
    assert result["container_title"] == "Journal of Things"
    assert result["links"] == [{"URL": "https://example.com/supp.pdf", "intended-application": "text-mining"}]
    assert result["resource_url"] == "https://example.com/paper"
    assert captured["url"].startswith("https://api.crossref.org/works/10.1038/xyz")
    await client.aclose()


@pytest.mark.asyncio
async def test_fetch_supplementary_info_from_doi_strips_doi_url_prefix():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"message": {"title": ["T"]}})

    client = _client(handler)
    adapters = LiteratureAdapters(client)

    await adapters.fetch_supplementary_info_from_doi({"doi": "https://doi.org/10.1038/xyz"})

    assert "10.1038/xyz" in captured["url"]
    assert "doi.org" not in captured["url"]
    await client.aclose()


@pytest.mark.asyncio
async def test_fetch_supplementary_info_from_doi_missing_doi_raises_value_error():
    adapters = LiteratureAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'doi'"):
        await adapters.fetch_supplementary_info_from_doi({})

    with pytest.raises(ValueError, match="non-empty 'doi'"):
        await adapters.fetch_supplementary_info_from_doi(None)


@pytest.mark.asyncio
async def test_fetch_supplementary_info_from_doi_404_raises_literature_api_error():
    client = _client(lambda r: httpx.Response(404, json={"error": "not found"}))
    adapters = LiteratureAdapters(client)

    with pytest.raises(LiteratureAPIError, match="was not found"):
        await adapters.fetch_supplementary_info_from_doi({"doi": "10.0000/nope"})
    await client.aclose()


@pytest.mark.asyncio
async def test_fetch_supplementary_info_from_doi_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = LiteratureAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.fetch_supplementary_info_from_doi({"doi": "10.1038/xyz"})
    await client.aclose()


@pytest.mark.asyncio
async def test_fetch_supplementary_info_from_doi_malformed_body_raises_literature_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = LiteratureAdapters(client)

    with pytest.raises(LiteratureAPIError, match="expected work metadata"):
        await adapters.fetch_supplementary_info_from_doi({"doi": "10.1038/xyz"})
    await client.aclose()


# --- query_arxiv -------------------------------------------------------------

_ARXIV_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1234.5678v1</id>
    <title>Attention Is All You Need Again</title>
    <summary>  A summary.  </summary>
    <published>2024-01-01T00:00:00Z</published>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
    <link title="pdf" href="http://arxiv.org/pdf/1234.5678v1" rel="related" type="application/pdf"/>
  </entry>
</feed>
"""


@pytest.mark.asyncio
async def test_query_arxiv_success_parses_entries():
    captured = {}

    def handler(request):
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, text=_ARXIV_FEED)

    client = _client(handler)
    adapters = LiteratureAdapters(client)

    result = await adapters.query_arxiv({"search_query": "all:transformers", "max_results": 5})

    assert len(result) == 1
    entry = result[0]
    assert entry["id"] == "http://arxiv.org/abs/1234.5678v1"
    assert entry["arxiv_id"] == "1234.5678v1"
    assert entry["title"] == "Attention Is All You Need Again"
    assert entry["summary"] == "A summary."
    assert entry["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert entry["pdf_url"] == "http://arxiv.org/pdf/1234.5678v1"
    assert captured["params"]["search_query"] == "all:transformers"
    assert captured["params"]["max_results"] == "5"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_arxiv_missing_args_raises_value_error():
    adapters = LiteratureAdapters(_client(lambda r: httpx.Response(200, text=_ARXIV_FEED)))

    with pytest.raises(ValueError, match="non-empty 'search_query'"):
        await adapters.query_arxiv({})

    with pytest.raises(ValueError, match="non-empty 'search_query'"):
        await adapters.query_arxiv(None)


@pytest.mark.asyncio
async def test_query_arxiv_accepts_id_list_only():
    client = _client(lambda r: httpx.Response(200, text=_ARXIV_FEED))
    adapters = LiteratureAdapters(client)

    result = await adapters.query_arxiv({"id_list": "1234.5678"})

    assert len(result) == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_query_arxiv_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = LiteratureAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_arxiv({"search_query": "all:x"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_arxiv_malformed_xml_raises_literature_api_error():
    client = _client(lambda r: httpx.Response(200, text="not xml at all <<<"))
    adapters = LiteratureAdapters(client)

    with pytest.raises(LiteratureAPIError, match="could not be parsed as XML"):
        await adapters.query_arxiv({"search_query": "all:x"})
    await client.aclose()


# --- query_scholar -------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_scholar_success_returns_papers():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "total": 1,
                "offset": 0,
                "data": [
                    {
                        "title": "Deep Learning",
                        "abstract": "An abstract.",
                        "year": 2020,
                        "authors": [{"name": "Yann LeCun"}],
                        "url": "https://semanticscholar.org/paper/1",
                        "externalIds": {"DOI": "10.1000/deep"},
                        "venue": "Nature",
                    }
                ],
            },
        )

    client = _client(handler)
    adapters = LiteratureAdapters(client)

    result = await adapters.query_scholar({"query": "deep learning"})

    assert result == [
        {
            "title": "Deep Learning",
            "abstract": "An abstract.",
            "year": 2020,
            "authors": ["Yann LeCun"],
            "url": "https://semanticscholar.org/paper/1",
            "doi": "10.1000/deep",
            "venue": "Nature",
        }
    ]
    await client.aclose()


@pytest.mark.asyncio
async def test_query_scholar_missing_query_raises_value_error():
    adapters = LiteratureAdapters(_client(lambda r: httpx.Response(200, json={"data": []})))

    with pytest.raises(ValueError, match="non-empty 'query'"):
        await adapters.query_scholar({})


@pytest.mark.asyncio
async def test_query_scholar_rate_limited_raises_literature_api_error():
    client = _client(lambda r: httpx.Response(429, text="rate limited"))
    adapters = LiteratureAdapters(client)

    with pytest.raises(LiteratureAPIError, match="rate-limited"):
        await adapters.query_scholar({"query": "deep learning"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_scholar_sends_api_key_header_when_configured(monkeypatch):
    captured = {}

    def handler(request):
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(literature_adapters_module.settings, "SEMANTIC_SCHOLAR_API_KEY", "s2-secret")
    client = _client(handler)
    adapters = LiteratureAdapters(client)

    await adapters.query_scholar({"query": "x"})

    assert captured["headers"]["x-api-key"] == "s2-secret"
    await client.aclose()


@pytest.mark.asyncio
async def test_query_scholar_malformed_body_raises_literature_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = LiteratureAdapters(client)

    with pytest.raises(LiteratureAPIError, match="expected result shape"):
        await adapters.query_scholar({"query": "x"})
    await client.aclose()


# --- query_pubmed -------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_pubmed_search_by_term_success():
    def handler(request):
        if "esearch" in str(request.url):
            return httpx.Response(200, json={"esearchresult": {"idlist": ["111"]}})
        if "esummary" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "uids": ["111"],
                        "111": {
                            "title": "A Pubmed Article",
                            "authors": [{"name": "Doe J"}],
                            "source": "Nature",
                            "pubdate": "2021",
                            "articleids": [{"idtype": "doi", "value": "10.1/xyz"}],
                        },
                    }
                },
            )
        return httpx.Response(500)

    client = _client(handler)
    adapters = LiteratureAdapters(client)

    result = await adapters.query_pubmed({"term": "cancer"})

    assert result == [
        {
            "pmid": "111",
            "title": "A Pubmed Article",
            "authors": ["Doe J"],
            "source": "Nature",
            "pubdate": "2021",
            "doi": "10.1/xyz",
        }
    ]
    await client.aclose()


@pytest.mark.asyncio
async def test_query_pubmed_by_pmids_skips_esearch():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(
            200,
            json={"result": {"uids": ["222"], "222": {"title": "T", "authors": [], "source": "S", "pubdate": "2020"}}},
        )

    client = _client(handler)
    adapters = LiteratureAdapters(client)

    result = await adapters.query_pubmed({"pmids": ["222"]})

    assert len(result) == 1
    assert all("esearch" not in c for c in calls)
    await client.aclose()


@pytest.mark.asyncio
async def test_query_pubmed_empty_search_returns_empty_list():
    client = _client(lambda r: httpx.Response(200, json={"esearchresult": {"idlist": []}}))
    adapters = LiteratureAdapters(client)

    result = await adapters.query_pubmed({"term": "zzzznonexistentqueryzzzz"})

    assert result == []
    await client.aclose()


@pytest.mark.asyncio
async def test_query_pubmed_missing_args_raises_value_error():
    adapters = LiteratureAdapters(_client(lambda r: httpx.Response(200, json={})))

    with pytest.raises(ValueError, match="non-empty 'term'"):
        await adapters.query_pubmed({})

    with pytest.raises(ValueError, match="non-empty 'term'"):
        await adapters.query_pubmed(None)


@pytest.mark.asyncio
async def test_query_pubmed_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = LiteratureAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.query_pubmed({"term": "cancer"})
    await client.aclose()


@pytest.mark.asyncio
async def test_query_pubmed_malformed_esearch_body_raises_literature_api_error():
    client = _client(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    adapters = LiteratureAdapters(client)

    with pytest.raises(LiteratureAPIError, match="esearch response"):
        await adapters.query_pubmed({"term": "cancer"})
    await client.aclose()


# --- search_google -------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_google_success_returns_items(monkeypatch):
    monkeypatch.setattr(literature_adapters_module.settings, "GOOGLE_SEARCH_API_KEY", "gkey")
    monkeypatch.setattr(literature_adapters_module.settings, "GOOGLE_SEARCH_ENGINE_ID", "gcx")

    captured = {}

    def handler(request):
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={"items": [{"title": "Result 1", "link": "https://example.com/1", "snippet": "Snippet 1"}]},
        )

    client = _client(handler)
    adapters = LiteratureAdapters(client)

    result = await adapters.search_google({"query": "openscientific workbench"})

    assert result == [{"title": "Result 1", "link": "https://example.com/1", "snippet": "Snippet 1"}]
    assert captured["params"]["key"] == "gkey"
    assert captured["params"]["cx"] == "gcx"
    assert captured["params"]["q"] == "openscientific workbench"
    await client.aclose()


@pytest.mark.asyncio
async def test_search_google_missing_query_raises_value_error(monkeypatch):
    monkeypatch.setattr(literature_adapters_module.settings, "GOOGLE_SEARCH_API_KEY", "gkey")
    monkeypatch.setattr(literature_adapters_module.settings, "GOOGLE_SEARCH_ENGINE_ID", "gcx")
    adapters = LiteratureAdapters(_client(lambda r: httpx.Response(200, json={"items": []})))

    with pytest.raises(ValueError, match="non-empty 'query'"):
        await adapters.search_google({})


@pytest.mark.asyncio
async def test_search_google_missing_credentials_raises_literature_api_error(monkeypatch):
    monkeypatch.setattr(literature_adapters_module.settings, "GOOGLE_SEARCH_API_KEY", None)
    monkeypatch.setattr(literature_adapters_module.settings, "GOOGLE_SEARCH_ENGINE_ID", None)
    adapters = LiteratureAdapters(_client(lambda r: httpx.Response(200, json={"items": []})))

    with pytest.raises(LiteratureAPIError, match="GOOGLE_SEARCH_API_KEY"):
        await adapters.search_google({"query": "x"})


@pytest.mark.asyncio
async def test_search_google_upstream_500_raises_http_error(monkeypatch):
    monkeypatch.setattr(literature_adapters_module.settings, "GOOGLE_SEARCH_API_KEY", "gkey")
    monkeypatch.setattr(literature_adapters_module.settings, "GOOGLE_SEARCH_ENGINE_ID", "gcx")
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = LiteratureAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.search_google({"query": "x"})
    await client.aclose()


# --- extract_url_content -------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_url_content_success_strips_scripts_and_returns_text():
    html = """
    <html>
      <head><title>  My Page  </title><style>body{color:red}</style></head>
      <body>
        <script>alert('x')</script>
        <h1>Hello</h1>
        <p>World</p>
      </body>
    </html>
    """

    captured = {}

    def handler(request):
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, text=html)

    client = _client(handler)
    adapters = LiteratureAdapters(client)

    result = await adapters.extract_url_content({"url": "https://example.com/page"})

    assert result["url"] == "https://example.com/page"
    assert result["title"] == "My Page"
    assert "Hello" in result["text"]
    assert "World" in result["text"]
    assert "alert" not in result["text"]
    assert "color:red" not in result["text"]
    assert captured["headers"]["user-agent"].startswith("OpenScientific-Workbench")
    await client.aclose()


@pytest.mark.asyncio
async def test_extract_url_content_missing_url_raises_value_error():
    adapters = LiteratureAdapters(_client(lambda r: httpx.Response(200, text="<html></html>")))

    with pytest.raises(ValueError, match="non-empty 'url'"):
        await adapters.extract_url_content({})

    with pytest.raises(ValueError, match="non-empty 'url'"):
        await adapters.extract_url_content(None)


@pytest.mark.asyncio
async def test_extract_url_content_404_raises_literature_api_error():
    client = _client(lambda r: httpx.Response(404, text="not found"))
    adapters = LiteratureAdapters(client)

    with pytest.raises(LiteratureAPIError, match="404"):
        await adapters.extract_url_content({"url": "https://example.com/missing"})
    await client.aclose()


@pytest.mark.asyncio
async def test_extract_url_content_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = LiteratureAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.extract_url_content({"url": "https://example.com/x"})
    await client.aclose()


@pytest.mark.asyncio
async def test_extract_url_content_empty_body_raises_literature_api_error():
    client = _client(lambda r: httpx.Response(200, text="   "))
    adapters = LiteratureAdapters(client)

    with pytest.raises(LiteratureAPIError, match="empty response body"):
        await adapters.extract_url_content({"url": "https://example.com/x"})
    await client.aclose()


# --- extract_pdf_content -------------------------------------------------------------


def _minimal_pdf_bytes() -> bytes:
    # A minimal, valid, single-page PDF with no text content -- enough for
    # pypdf's `PdfReader` to open successfully and yield an empty text layer,
    # without needing to check in a real binary fixture file.
    return (
        b"%PDF-1.1\n"
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
        b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n"
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n"
        b"trailer<< /Size 4 /Root 1 0 R >>\n"
        b"startxref\n0\n%%EOF"
    )


@pytest.mark.asyncio
async def test_extract_pdf_content_from_url_no_text_layer_raises_literature_api_error():
    client = _client(lambda r: httpx.Response(200, content=_minimal_pdf_bytes()))
    adapters = LiteratureAdapters(client)

    with pytest.raises(LiteratureAPIError, match="No extractable text layer"):
        await adapters.extract_pdf_content({"url": "https://example.com/paper.pdf"})
    await client.aclose()


@pytest.mark.asyncio
async def test_extract_pdf_content_missing_args_raises_value_error():
    adapters = LiteratureAdapters(_client(lambda r: httpx.Response(200, content=b"")))

    with pytest.raises(ValueError, match="non-empty 'url'"):
        await adapters.extract_pdf_content({})

    with pytest.raises(ValueError, match="non-empty 'url'"):
        await adapters.extract_pdf_content(None)


@pytest.mark.asyncio
async def test_extract_pdf_content_404_raises_literature_api_error():
    client = _client(lambda r: httpx.Response(404, text="not found"))
    adapters = LiteratureAdapters(client)

    with pytest.raises(LiteratureAPIError, match="was not found"):
        await adapters.extract_pdf_content({"url": "https://example.com/missing.pdf"})
    await client.aclose()


@pytest.mark.asyncio
async def test_extract_pdf_content_upstream_500_raises_http_error():
    client = _client(lambda r: httpx.Response(500, text="server error"))
    adapters = LiteratureAdapters(client)

    with pytest.raises(httpx.HTTPStatusError):
        await adapters.extract_pdf_content({"url": "https://example.com/paper.pdf"})
    await client.aclose()


@pytest.mark.asyncio
async def test_extract_pdf_content_invalid_pdf_bytes_raises_literature_api_error():
    client = _client(lambda r: httpx.Response(200, content=b"not a pdf at all"))
    adapters = LiteratureAdapters(client)

    with pytest.raises(LiteratureAPIError, match="not a valid, readable PDF"):
        await adapters.extract_pdf_content({"url": "https://example.com/paper.pdf"})
    await client.aclose()


@pytest.mark.asyncio
async def test_extract_pdf_content_invalid_base64_raises_value_error():
    adapters = LiteratureAdapters(_client(lambda r: httpx.Response(200, content=b"")))

    with pytest.raises(ValueError, match="not valid base64"):
        await adapters.extract_pdf_content({"pdf_base64": "not-valid-base64!!"})


@pytest.mark.asyncio
async def test_extract_pdf_content_inline_base64_no_network_call():
    called = {"count": 0}

    def handler(request):
        called["count"] += 1
        return httpx.Response(200, content=b"")

    client = _client(handler)
    adapters = LiteratureAdapters(client)
    encoded = base64.b64encode(_minimal_pdf_bytes()).decode("ascii")

    with pytest.raises(LiteratureAPIError, match="No extractable text layer"):
        await adapters.extract_pdf_content({"pdf_base64": encoded})

    assert called["count"] == 0
    await client.aclose()


# --- register_literature_tools -------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_literature_tools_registers_all_seven_tools():
    registry = MCPServerRegistry()

    registered = register_literature_tools(registry)

    assert set(registered) == {
        "fetch_supplementary_info_from_doi",
        "query_arxiv",
        "query_scholar",
        "query_pubmed",
        "search_google",
        "extract_url_content",
        "extract_pdf_content",
    }
    assert set(registered).issubset(registry.registry.keys())


@pytest.mark.asyncio
async def test_register_literature_tools_makes_arxiv_tool_routable():
    client = _client(lambda r: httpx.Response(200, text=_ARXIV_FEED))
    registry = MCPServerRegistry()

    register_literature_tools(registry, client)

    out = await registry.route("query_arxiv", {"search_query": "all:x"})
    assert "Attention Is All You Need Again" in out
    await client.aclose()
