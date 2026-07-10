"""RNF-007: get_storage_manager() must read the USE_BTRFS flag from config
instead of hardcoding it, so a Linux+Btrfs host can actually enable CoW forks.

We spy on the constructor argument (platform-independent) rather than the
manager's final ``use_btrfs`` attribute, which self-disables off Linux.
"""
import src.presentation.routes.workspaces as ws_module
from src.infrastructure.config import settings


def _spy(monkeypatch):
    captured = {}

    class SpyManager:
        def __init__(self, use_btrfs: bool = False):
            captured["use_btrfs"] = use_btrfs

    monkeypatch.setattr(ws_module, "BtrfsSnapshotManager", SpyManager)
    return captured


def test_get_storage_manager_enables_btrfs_when_config_true(monkeypatch):
    captured = _spy(monkeypatch)
    monkeypatch.setattr(settings, "USE_BTRFS", True)

    ws_module.get_storage_manager()

    assert captured["use_btrfs"] is True


def test_get_storage_manager_disables_btrfs_when_config_false(monkeypatch):
    captured = _spy(monkeypatch)
    monkeypatch.setattr(settings, "USE_BTRFS", False)

    ws_module.get_storage_manager()

    assert captured["use_btrfs"] is False
