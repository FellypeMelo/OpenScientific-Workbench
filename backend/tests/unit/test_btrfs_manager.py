"""
Tests for `BtrfsSnapshotManager` (Fase 4).

Covers:
- The real Btrfs `subprocess.run(["btrfs", "subvolume", "snapshot", ...])` path
  (mocked at the subprocess boundary -- there is no live Btrfs filesystem in
  this sandbox), including the `CalledProcessError` -> `OSError` wrapping.
- The non-btrfs fallback's correctness fix: a missing or non-directory source
  path now raises a clear exception instead of silently creating an empty
  target directory and calling it a success (the previous "mock directory
  creation" behavior masked what would otherwise be a real bug upstream).
"""
import os
import shutil
import subprocess
import tempfile

import pytest

from src.infrastructure.storage.btrfs_manager import BtrfsSnapshotManager


@pytest.mark.asyncio
async def test_btrfs_real_subprocess_path_invokes_btrfs_snapshot(monkeypatch):
    """Exercises the real (Linux) `btrfs subvolume snapshot` branch by mocking
    `subprocess.run` -- there is no live Btrfs filesystem available here."""
    manager = BtrfsSnapshotManager(use_btrfs=False)
    manager.use_btrfs = True  # bypass the `sys.platform` gate for this test

    calls = []

    def fake_run(cmd, check, capture_output):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    await manager.create_snapshot("/workspaces/parent", "/workspaces/child")

    assert calls == [["btrfs", "subvolume", "snapshot", "/workspaces/parent", "/workspaces/child"]]


@pytest.mark.asyncio
async def test_btrfs_real_subprocess_path_wraps_failure_as_oserror(monkeypatch):
    manager = BtrfsSnapshotManager(use_btrfs=False)
    manager.use_btrfs = True

    def fake_run(cmd, check, capture_output):
        raise subprocess.CalledProcessError(
            returncode=1, cmd=cmd, stderr=b"ERROR: not a Btrfs filesystem"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(OSError, match="not a Btrfs filesystem"):
        await manager.create_snapshot("/workspaces/parent", "/workspaces/child")


@pytest.mark.asyncio
async def test_fallback_raises_filenotfound_when_source_missing():
    manager = BtrfsSnapshotManager(use_btrfs=False)
    with tempfile.TemporaryDirectory() as tmp:
        source = os.path.join(tmp, "does_not_exist")
        target = os.path.join(tmp, "child")

        with pytest.raises(FileNotFoundError, match="does not exist"):
            await manager.create_snapshot(source, target)

        assert not os.path.exists(target)


@pytest.mark.asyncio
async def test_fallback_raises_notadirectory_when_source_is_a_file():
    manager = BtrfsSnapshotManager(use_btrfs=False)
    with tempfile.TemporaryDirectory() as tmp:
        source = os.path.join(tmp, "not_a_dir.txt")
        with open(source, "w") as f:
            f.write("just a file, not a workspace directory")
        target = os.path.join(tmp, "child")

        with pytest.raises(NotADirectoryError, match="not a directory"):
            await manager.create_snapshot(source, target)

        assert not os.path.exists(target)


@pytest.mark.asyncio
async def test_fallback_copies_real_directory_contents():
    manager = BtrfsSnapshotManager(use_btrfs=False)
    with tempfile.TemporaryDirectory() as tmp:
        source = os.path.join(tmp, "parent")
        target = os.path.join(tmp, "child")
        os.makedirs(os.path.join(source, "nested"))
        with open(os.path.join(source, "file.txt"), "w") as f:
            f.write("data")
        with open(os.path.join(source, "nested", "inner.txt"), "w") as f:
            f.write("nested-data")

        await manager.create_snapshot(source, target)

        with open(os.path.join(target, "file.txt")) as f:
            assert f.read() == "data"
        with open(os.path.join(target, "nested", "inner.txt")) as f:
            assert f.read() == "nested-data"


@pytest.mark.asyncio
async def test_fallback_overwrites_preexisting_target():
    manager = BtrfsSnapshotManager(use_btrfs=False)
    with tempfile.TemporaryDirectory() as tmp:
        source = os.path.join(tmp, "parent")
        target = os.path.join(tmp, "child")
        os.makedirs(source)
        with open(os.path.join(source, "new.txt"), "w") as f:
            f.write("new-data")

        # Pre-existing target with stale content that must be replaced, not merged.
        os.makedirs(target)
        with open(os.path.join(target, "stale.txt"), "w") as f:
            f.write("stale-data")

        await manager.create_snapshot(source, target)

        assert os.path.exists(os.path.join(target, "new.txt"))
        assert not os.path.exists(os.path.join(target, "stale.txt"))
