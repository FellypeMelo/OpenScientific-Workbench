"""Path-containment guard against traversal / absolute-path escapes (RNF-002,
CWE-22, CVE-2026-7398).

The previous inline checks (`".." in s`, `s.startswith("/"/"\\")`) missed
Windows drive-letter absolute paths such as ``C:\\Windows`` -- a live bypass on
the project's own target OS. This guard resolves the mandated strict containment
by checking BOTH POSIX and Windows conventions, so it behaves identically on the
Linux CI runner and the Windows dev box.
"""
import ntpath
import posixpath
import re

_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class PathTraversalError(ValueError):
    """Raised when a candidate path is absolute or attempts directory traversal."""


def ensure_safe_relative_path(candidate: object) -> str:
    """Return a normalized, root-relative POSIX path, or raise PathTraversalError.

    Rejects empty input, null bytes, absolute paths (either OS convention),
    Windows drive specifications, and any ``..`` component.
    """
    if candidate is None:
        raise PathTraversalError("A path is required.")

    cleaned = str(candidate).strip()
    if not cleaned:
        raise PathTraversalError("Empty path is not allowed.")
    if "\x00" in cleaned:
        raise PathTraversalError("Null byte in path is not allowed.")

    # Unify separators so a leading slash catches POSIX roots (/etc) AND Windows
    # backslash/UNC roots (\\server, \windows) on any host OS.
    unified = cleaned.replace("\\", "/")
    # Absolute in either convention, or a Windows drive spec (incl. drive-relative
    # 'C:foo', which ntpath.isabs does not flag).
    if (
        unified.startswith("/")
        or posixpath.isabs(cleaned)
        or ntpath.isabs(cleaned)
        or _DRIVE_RE.match(cleaned)
    ):
        raise PathTraversalError(f"Absolute paths are not allowed: {cleaned!r}")

    parts = unified.split("/")
    if any(part == ".." for part in parts):
        raise PathTraversalError(f"Path traversal ('..') is not allowed: {cleaned!r}")

    normalized = posixpath.normpath("/".join(p for p in parts if p not in ("", ".")))
    # Defense in depth: normpath must not have produced an escape.
    if normalized.startswith("..") or posixpath.isabs(normalized):
        raise PathTraversalError(f"Path escapes the workspace root: {cleaned!r}")

    return normalized
