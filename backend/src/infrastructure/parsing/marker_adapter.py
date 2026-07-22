"""Optional, heavier OCR-grade PDF-parsing adapter (RAG-MARKER): Marker
(https://github.com/datalab-to/marker), which uses layout/OCR models (torch)
to convert scanned or complex-layout PDFs to Markdown far more accurately
than a plain text-layer extractor like `pypdf_adapter.py` can -- at the cost
of a large optional dependency (torch + downloaded model weights).

Kept strictly opt-in per this project's locked architecture ("Marker OCR is
an optional heavier upgrade behind a flag, not required for basic ingestion
to work"): `marker-pdf`/`torch` are deliberately NOT declared in
`pyproject.toml`'s default dependency set, and the import below is deferred
to `parse()` (never at module import time), so importing this module -- and
therefore this whole package -- never requires them to be installed.

Both "disabled via `MARKER_ENABLED`" and "enabled but the optional package
isn't installed" raise `MarkerNotConfiguredError` with a clear, actionable
message -- never a silent fallback to `pypdf_adapter`'s output or fabricated
text. A caller that specifically asked for OCR-grade parsing must know when
it did not actually get it (this project's sandboxing ground rule -- "fail
loud rather than silently degrade" -- applies here for the same reason: an
operator who flipped `MARKER_ENABLED=true` expecting real Marker output must
not silently get pypdf's weaker text-layer extraction instead).

The real invocation path (`PdfConverter`/`create_model_dict`, verified
current via Context7 -- https://context7.com/datalab-to/marker) is only ever
reached once BOTH `MARKER_ENABLED=true` AND the optional `marker-pdf`
package is actually importable; it is not independently exercised by this
project's test suite (no torch/marker-pdf install in this environment), same
scope boundary as `TectonicCompiler`'s real `tectonic` binary invocation.
"""
import asyncio
import tempfile
from pathlib import Path

from src.domain.ports.document_parser import DocumentParserPort
from src.infrastructure.config import settings


class MarkerNotConfiguredError(RuntimeError):
    """Raised when Marker OCR parsing is requested but unusable: either
    `MARKER_ENABLED=false` (the default) or the optional `marker-pdf`
    package is not installed."""


class MarkerDocumentParser(DocumentParserPort):
    async def parse(self, pdf_bytes: bytes) -> str:
        if not settings.MARKER_ENABLED:
            raise MarkerNotConfiguredError(
                "Marker OCR parsing is disabled (MARKER_ENABLED=false, the "
                "default). Set MARKER_ENABLED=true and install the optional "
                "'marker-pdf' package to enable it, or use the default "
                "pypdf-based parser (infrastructure/parsing/pypdf_adapter.py)."
            )

        try:
            from marker.converters.pdf import PdfConverter
            from marker.models import create_model_dict
        except ImportError as exc:
            raise MarkerNotConfiguredError(
                "MARKER_ENABLED=true but the optional 'marker-pdf' package "
                "(and its torch dependency) is not installed in this "
                "environment. Install it (`pip install marker-pdf`) or set "
                "MARKER_ENABLED=false to fall back to the default pypdf "
                "parser."
            ) from exc

        return await asyncio.to_thread(_convert_sync, pdf_bytes, PdfConverter, create_model_dict)


def _convert_sync(pdf_bytes: bytes, PdfConverter, create_model_dict) -> str:
    # Marker's `PdfConverter` takes a file PATH, not raw bytes -- its PDF
    # provider needs a real file on disk. Materialize the upload into a temp
    # file for the duration of the conversion only (same "write to a temp
    # path for a subprocess/library that needs one" pattern
    # `TectonicCompiler` uses, just via a library call instead of a
    # subprocess).
    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = Path(tmp_dir) / "document.pdf"
        pdf_path.write_bytes(pdf_bytes)

        artifact_dict = create_model_dict()
        converter = PdfConverter(artifact_dict)
        output = converter(str(pdf_path))
        return output.markdown
