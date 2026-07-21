"""Default (RAG-MARKER) PDF text-extraction adapter: `pypdf`, pure Python, no
GPU/model download -- genuinely extracts a real PDF's embedded text layer
today, no infra required. `MarkerDocumentParser` (see `marker_adapter.py`) is
the optional, heavier OCR-grade alternative for scanned/complex PDFs.
"""
import asyncio
import io

from pypdf import PdfReader

from src.domain.ports.document_parser import DocumentParserPort


class PypdfDocumentParser(DocumentParserPort):
    """Extracts each page's text layer and joins them with a blank line
    between pages (so the paragraph-boundary chunker in
    `infrastructure/parsing/chunker.py` treats a page break like a paragraph
    break)."""

    async def parse(self, pdf_bytes: bytes) -> str:
        # `pypdf`'s parsing is CPU-bound/blocking; offload it to a worker
        # thread so `await`ing this from an async route never blocks the
        # event loop for the duration of parsing a (potentially large) PDF.
        return await asyncio.to_thread(self._parse_sync, pdf_bytes)

    @staticmethod
    def _parse_sync(pdf_bytes: bytes) -> str:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages_text = []
        for page in reader.pages:
            text = (page.extract_text() or "").strip()
            if text:
                pages_text.append(text)
        return "\n\n".join(pages_text)
