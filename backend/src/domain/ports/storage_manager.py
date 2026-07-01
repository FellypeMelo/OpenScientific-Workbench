from typing import Protocol

class StorageManagerPort(Protocol):
    """
    Domain port interface for Copy-on-Write physical storage operations (Btrfs/ZFS).
    """
    async def create_snapshot(self, source_path: str, target_path: str) -> None:
        """Executes a zero-copy physical snapshot of a workspace directory."""
        ...
