"""Unit tests for `scripts/fetch_data_lake.py`'s `_download` decompression
logic -- no real network, `urllib.request.urlopen` is faked at the transport
boundary (same convention as `httpx.MockTransport` elsewhere in this repo)."""
import gzip
import io
import zipfile

import pytest

import scripts.fetch_data_lake as fetch_data_lake


def _fake_urlopen(payload: bytes):
    def _opener(request, timeout=120):
        return io.BytesIO(payload)

    return _opener


def test_download_plain_file_no_decompress(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_data_lake.urllib.request, "urlopen", _fake_urlopen(b"hello"))
    dest = tmp_path / "out.txt"

    fetch_data_lake._download("http://example.test/x", dest, decompress=None)

    assert dest.read_bytes() == b"hello"


def test_download_gzip_decompresses(tmp_path, monkeypatch):
    payload = gzip.compress(b"gzipped content")
    monkeypatch.setattr(fetch_data_lake.urllib.request, "urlopen", _fake_urlopen(payload))
    dest = tmp_path / "out.csv"

    fetch_data_lake._download("http://example.test/x.gz", dest, decompress="gzip")

    assert dest.read_bytes() == b"gzipped content"


def test_download_zip_extracts_largest_member(tmp_path, monkeypatch):
    """The GWAS Catalog switched its stable release format to a zip archive
    containing exactly one data file (see `_AUTO_DOWNLOADS`) -- "largest
    member" is a defensive tie-breaker for a hypothetical future manifest/
    README alongside it, not real ambiguity today."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("README.txt", "short")
        zf.writestr("data.tsv", "a lot more content than the readme")
    monkeypatch.setattr(fetch_data_lake.urllib.request, "urlopen", _fake_urlopen(buf.getvalue()))
    dest = tmp_path / "out.tsv"

    fetch_data_lake._download("http://example.test/x.zip", dest, decompress="zip")

    assert dest.read_bytes() == b"a lot more content than the readme"


def test_download_zip_raises_on_empty_archive(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w"):
        pass
    monkeypatch.setattr(fetch_data_lake.urllib.request, "urlopen", _fake_urlopen(buf.getvalue()))
    dest = tmp_path / "out.tsv"

    with pytest.raises(ValueError, match="empty zip"):
        fetch_data_lake._download("http://example.test/x.zip", dest, decompress="zip")
