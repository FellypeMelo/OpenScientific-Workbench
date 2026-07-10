"""Unit tests for the path-containment guard (RNF-002).

Closes the substring-denylist gaps flagged by the audit: Windows drive-letter
absolute paths (C:\\...) and mixed separators must be rejected regardless of the
OS running the test (the guard checks BOTH posix and windows conventions).
"""
import pytest

from src.domain.services.path_guard import PathTraversalError, ensure_safe_relative_path


@pytest.mark.parametrize(
    "good",
    ["workspace_123", "sub/dir/file.py", "./nested/script.py", "a/b/c"],
)
def test_accepts_contained_relative_paths(good):
    result = ensure_safe_relative_path(good)
    assert ".." not in result
    assert not result.startswith("/")


@pytest.mark.parametrize(
    "bad",
    [
        "../escape",
        "a/../../etc/passwd",
        "workspaces/..",
        "/etc/passwd",
        "\\\\server\\share",
        "C:\\Windows\\System32\\config\\SAM",  # windows drive-letter (the bypass)
        "C:/Windows/System32",
        "C:relative",  # drive-relative
        "",
        "   ",
        "with\x00null",
    ],
)
def test_rejects_traversal_and_absolute_paths(bad):
    with pytest.raises(PathTraversalError):
        ensure_safe_relative_path(bad)
