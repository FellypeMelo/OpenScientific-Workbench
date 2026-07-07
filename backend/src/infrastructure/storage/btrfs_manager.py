import subprocess
import shutil
import os
import sys
from src.domain.ports.storage_manager import StorageManagerPort

class BtrfsSnapshotManager(StorageManagerPort):
    """
    Adapter implementing StorageManagerPort.
    Executes a Copy-on-Write (CoW) Btrfs snapshot.
    Falls back to a real recursive directory copy (`shutil.copytree`) on
    non-btrfs/non-linux filesystems (e.g. Windows dev machine) -- not a CoW
    snapshot, but a genuine, complete copy of the workspace contents.

    `source_path` must be an existing directory: `ForkWorkspaceUseCase` always
    forks an already-persisted parent workspace's `fs_mount_path`, so a
    missing/non-directory source indicates a real bug upstream (wrong path,
    workspace never materialized on disk, etc.), not "nothing to copy yet".
    Silently creating an empty target directory in that case would hide the
    bug and hand the caller a child workspace that looks forked but is
    actually empty -- so both cases raise instead.
    """
    def __init__(self, use_btrfs: bool = False):
        self.use_btrfs = use_btrfs and sys.platform.startswith("linux")

    async def create_snapshot(self, source_path: str, target_path: str) -> None:
        if self.use_btrfs:
            try:
                subprocess.run(
                    ["btrfs", "subvolume", "snapshot", source_path, target_path],
                    check=True,
                    capture_output=True
                )
            except subprocess.CalledProcessError as e:
                raise OSError(f"Btrfs snapshot failed: {e.stderr.decode()}")
        else:
            # Dev environment fallback (e.g., Windows NTFS, NTFS has no Btrfs).
            if not os.path.exists(source_path):
                raise FileNotFoundError(
                    f"Cannot snapshot workspace: source path '{source_path}' does not exist."
                )
            if not os.path.isdir(source_path):
                raise NotADirectoryError(
                    f"Cannot snapshot workspace: source path '{source_path}' exists but is not a directory."
                )

            if os.path.exists(target_path):
                shutil.rmtree(target_path)

            # Perform a real, complete directory copy (no CoW available here).
            shutil.copytree(source_path, target_path)
