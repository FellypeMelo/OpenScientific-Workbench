"""Reproducibility hashing (RNF-006).

Computes the SHA-256 of the dependency lockfile (``uv.lock`` /
``environment.yaml``) so it can be embedded into a produced artifact's metadata,
tying every result to the exact environment that generated it.
"""
import hashlib
from pathlib import Path

_CHUNK = 65536

# `reproducibility.py` lives at `backend/src/domain/services/reproducibility.py`,
# so its third ancestor is `backend/` itself -- resolved from this module's own
# location (not the caller's `cwd`) so it works the same way regardless of which
# directory the process was launched from.
_BACKEND_ROOT = Path(__file__).resolve().parents[3]


def compute_lockfile_hash(lockfile_path: str) -> str:
    """Return the lowercase hex SHA-256 of the lockfile at ``lockfile_path``.

    Raises FileNotFoundError if the lockfile is absent (a missing lockfile means
    the environment is not pinned, which callers must treat as an error).
    """
    digest = hashlib.sha256()
    with open(lockfile_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_lockfile_path() -> str:
    """Path to this backend's own ``uv.lock`` (RNF-006), resolved the same way
    ``tests/unit/test_reproducibility_service.py`` locates it: relative to this
    module's file location, never accepted as caller-supplied input. Used by
    ``SubmitTaskUseCase`` to stamp every produced ``ScientificArtifact`` with a
    hash of the exact environment that generated it, instead of trusting a
    caller-supplied path string."""
    return str(_BACKEND_ROOT / "uv.lock")
