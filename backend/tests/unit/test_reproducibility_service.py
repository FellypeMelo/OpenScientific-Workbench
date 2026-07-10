"""Unit tests for reproducibility hashing (RNF-006).

Replaces the tautological tests/retroactive/test_reproducibility.py (which hashed
a throwaway function and only checked uv.lock exists) with real coverage: the
lockfile's SHA-256 is computed and stamped onto the produced artifact.
"""
import hashlib
import re
from pathlib import Path
from uuid import uuid4

import pytest

from src.domain.entities.scientific_artifact import ScientificArtifact
from src.domain.services.reproducibility import compute_lockfile_hash

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_compute_lockfile_hash_matches_raw_sha256(tmp_path):
    lockfile = tmp_path / "uv.lock"
    lockfile.write_bytes(b"package==1.0.0\n")

    assert compute_lockfile_hash(str(lockfile)) == hashlib.sha256(b"package==1.0.0\n").hexdigest()


def test_real_backend_uv_lock_hashes_to_valid_sha256():
    digest = compute_lockfile_hash(str(_BACKEND_ROOT / "uv.lock"))
    assert re.match(r"^[0-9a-f]{64}$", digest)


def test_missing_lockfile_raises():
    with pytest.raises(FileNotFoundError):
        compute_lockfile_hash("this_lockfile_does_not_exist.lock")


def test_from_generated_output_stamps_lockfile_hash(tmp_path):
    lockfile = tmp_path / "uv.lock"
    lockfile.write_bytes(b"reproducible-bytes")

    artifact = ScientificArtifact.from_generated_output(
        session_id=uuid4(), name="affinity_plot.png", lockfile_path=str(lockfile)
    )

    assert artifact.name == "affinity_plot.png"
    assert artifact.sha256_hash == hashlib.sha256(b"reproducible-bytes").hexdigest()
