"""Reproducibility hashing (RNF-006).

Computes the SHA-256 of the dependency lockfile (``uv.lock`` /
``environment.yaml``) so it can be embedded into a produced artifact's metadata,
tying every result to the exact environment that generated it.
"""
import hashlib

_CHUNK = 65536


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
