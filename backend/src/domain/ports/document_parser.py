from typing import Protocol


class DocumentParserPort(Protocol):
    """Extracts plain text from raw PDF bytes (RAG-MARKER).

    Two adapters implement this: `infrastructure/parsing/pypdf_adapter.py`
    (the default -- pure Python, no GPU/model download) and
    `infrastructure/parsing/marker_adapter.py` (optional OCR-grade parsing,
    gated behind `settings.MARKER_ENABLED`).
    """

    async def parse(self, pdf_bytes: bytes) -> str:
        """Returns the extracted plain text of the document."""
        ...
