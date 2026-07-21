"""Test-only helper: builds a minimal, genuinely-valid single-page PDF
(hand-rolled PDF 1.4 object structure, no external PDF-authoring library
available in this project's dependency set) containing a real text content
stream -- so `PypdfDocumentParser`/ingestion tests exercise real `pypdf`
parsing against real PDF bytes, not a mocked parser.

Verified end-to-end against the installed `pypdf` in this repo: `PdfReader`
successfully parses the output and `page.extract_text()` returns exactly the
text passed in. Not a test module itself (no ``test_`` prefix), just a
fixture builder imported by the real test modules.
"""


def build_minimal_pdf(text: str) -> bytes:
    text_bytes = text.encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream_content = b"BT /F1 24 Tf 72 700 Td (" + text_bytes + b") Tj ET"
    objects.append(
        b"<< /Length " + str(len(stream_content)).encode() + b" >>\nstream\n" + stream_content + b"\nendstream"
    )

    out = bytearray()
    out += b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += b"trailer\n"
    out += f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    out += b"startxref\n"
    out += f"{xref_offset}\n".encode()
    out += b"%%EOF"
    return bytes(out)
