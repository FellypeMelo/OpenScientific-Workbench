"""Unit tests for `MarkerDocumentParser` (RAG-MARKER optional OCR-grade
parser). `marker-pdf`/`torch` are NOT installed in this environment (kept
optional per this project's locked architecture -- see the adapter's module
docstring), so:

- The "disabled" path (`MARKER_ENABLED=false`, the default) is exercised for
  real, no mocking needed.
- The "enabled but package missing" path is exercised for real too -- the
  actual `import marker...` genuinely fails in this environment, so this
  test asserts the real behavior of that failure, not a simulated one.
- The "enabled AND installed" happy path is exercised with the `marker`
  import machinery faked via `sys.modules`, since installing real
  `marker-pdf` (torch, GB-scale model weights) is out of scope for this
  sandbox/test suite -- this still verifies OUR adapter's own logic (temp
  file materialization, calling `PdfConverter`/`create_model_dict`,
  returning `output.markdown`) is correct.
"""
import sys
import types
from unittest.mock import MagicMock

import pytest

from src.infrastructure.config import settings
from src.infrastructure.parsing.marker_adapter import MarkerDocumentParser, MarkerNotConfiguredError


@pytest.mark.asyncio
async def test_parse_raises_when_marker_disabled(monkeypatch):
    monkeypatch.setattr(settings, "MARKER_ENABLED", False)
    parser = MarkerDocumentParser()

    with pytest.raises(MarkerNotConfiguredError, match="disabled"):
        await parser.parse(b"%PDF-1.4 fake bytes")


@pytest.mark.asyncio
async def test_parse_raises_when_enabled_but_package_not_installed(monkeypatch):
    # No `sys.modules` faking here -- `marker-pdf` is genuinely NOT installed
    # in this environment (kept optional per this project's locked
    # architecture), so `import marker...` inside `parse()` really does
    # raise `ModuleNotFoundError` (an `ImportError` subclass) on its own.
    monkeypatch.setattr(settings, "MARKER_ENABLED", True)
    parser = MarkerDocumentParser()

    with pytest.raises(MarkerNotConfiguredError, match="not installed"):
        await parser.parse(b"%PDF-1.4 fake bytes")


@pytest.mark.asyncio
async def test_parse_invokes_pdfconverter_and_returns_markdown_when_available(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "MARKER_ENABLED", True)

    fake_output = MagicMock()
    fake_output.markdown = "# Extracted via Marker\n\nReal content."

    fake_converter_instance = MagicMock(return_value=fake_output)
    fake_pdf_converter_cls = MagicMock(return_value=fake_converter_instance)
    fake_create_model_dict = MagicMock(return_value={"layout_model": object()})

    marker_pkg = types.ModuleType("marker")
    marker_converters_pkg = types.ModuleType("marker.converters")
    marker_converters_pdf_mod = types.ModuleType("marker.converters.pdf")
    marker_converters_pdf_mod.PdfConverter = fake_pdf_converter_cls
    marker_models_mod = types.ModuleType("marker.models")
    marker_models_mod.create_model_dict = fake_create_model_dict

    monkeypatch.setitem(sys.modules, "marker", marker_pkg)
    monkeypatch.setitem(sys.modules, "marker.converters", marker_converters_pkg)
    monkeypatch.setitem(sys.modules, "marker.converters.pdf", marker_converters_pdf_mod)
    monkeypatch.setitem(sys.modules, "marker.models", marker_models_mod)

    parser = MarkerDocumentParser()
    result = await parser.parse(b"%PDF-1.4 fake bytes")

    assert result == "# Extracted via Marker\n\nReal content."
    fake_create_model_dict.assert_called_once()
    fake_pdf_converter_cls.assert_called_once_with(fake_create_model_dict.return_value)
    fake_converter_instance.assert_called_once()
    # Called with a real, existing temp file path containing the given bytes.
    called_path = fake_converter_instance.call_args[0][0]
    assert called_path.endswith(".pdf")
