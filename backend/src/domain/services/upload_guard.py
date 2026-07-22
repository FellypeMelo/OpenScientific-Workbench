"""Shared multipart file-upload guards (pure domain logic, framework-agnostic
-- no FastAPI/Starlette import here, mirroring `path_guard.py`'s
``PathTraversalError`` convention: this raises plain, importable exceptions
and leaves mapping them to an HTTP status code to the presentation-layer
route, the same "raise a domain error, let the route translate it" shape
every other guard in this codebase already uses).

Two independent trust boundaries every file-upload route in this codebase
must cross the same way:

1. `sanitize_upload_filename` -- an uploaded file's client-supplied name is
   attacker-controlled metadata that is never sanitized for you; it must be
   reduced to a bare basename before it is ever used to build a filesystem
   path or logged.
2. `iter_upload_bounded` -- stream the upload in bounded chunks, raising the
   instant the cumulative size exceeds a caller-supplied cap, instead of
   buffering an unbounded body into memory/disk first.

First introduced for `POST /workspaces/{id}/files`
(`presentation/routes/workspaces.py`, which streams each chunk straight to
disk); reused as-is by `POST /api/v1/documents/ingest`
(`presentation/routes/documents.py`, which instead accumulates the bounded
chunks in memory -- a PDF parser needs the whole file's bytes at once) so
both routes enforce identically rather than each re-implementing its own
size cap / filename sanitization.
"""
import os
from typing import AsyncIterator, Optional, Protocol


class InvalidUploadFilenameError(ValueError):
    """Raised when an uploaded file's name sanitizes down to nothing usable
    (empty, or exactly ``"."``/``".."``)."""


class UploadTooLargeError(ValueError):
    """Raised the instant a bounded read's cumulative size exceeds the
    caller-supplied ``max_bytes`` cap."""


UPLOAD_CHUNK_BYTES = 1024 * 1024


def sanitize_upload_filename(raw_filename: Optional[str], default: str = "upload.bin") -> str:
    """Reduces an attacker-controlled multipart filename to a safe bare
    basename (e.g. ``"../../evil.sh"`` -> ``"evil.sh"``)."""
    raw_name = (raw_filename or default).replace("\\", "/")
    safe_name = os.path.basename(raw_name)
    if not safe_name or safe_name in (".", ".."):
        raise InvalidUploadFilenameError(f"Invalid upload filename: {raw_filename!r}")
    return safe_name


class _AsyncReadable(Protocol):
    """Structural type for anything shaped like FastAPI's ``UploadFile``
    (which this module deliberately does not import) -- just needs an async
    ``read(size)``."""

    async def read(self, size: int = -1) -> bytes: ...


async def iter_upload_bounded(
    file: _AsyncReadable, max_bytes: int, chunk_bytes: int = UPLOAD_CHUNK_BYTES
) -> AsyncIterator[bytes]:
    """Yields ``file``'s content in bounded chunks, raising
    ``UploadTooLargeError`` the instant the cumulative size exceeds
    ``max_bytes`` -- caps worst-case memory/disk use at the caller regardless
    of how large the attacker-supplied body claims (or attempts) to be."""
    total_bytes = 0
    while True:
        chunk = await file.read(chunk_bytes)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise UploadTooLargeError(f"Upload exceeds max_bytes={max_bytes}.")
        yield chunk
