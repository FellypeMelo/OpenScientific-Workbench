import pytest
import os
from src.infrastructure.graph.neo4j_client import Neo4jGraphClient
from src.infrastructure.security.vault_client import VaultClient
from src.infrastructure.sandbox.gvisor_driver import GVisorSandboxDriver
from src.infrastructure.hpc.slurm_dispatcher import SlurmSSHDispatcher
from src.infrastructure.mcp.server_registry import MCPServerRegistry
from src.infrastructure.storage.btrfs_manager import BtrfsSnapshotManager

@pytest.mark.asyncio
async def test_neo4j_client_mock():
    client = Neo4jGraphClient(uri="bolt://mock-neo4j:7687", password="")
    await client.add_triple("TP53", "interacts_with", "MDM2")
    relations = await client.get_relations("TP53")
    assert len(relations) == 1
    assert relations[0]["object"] == "MDM2"

@pytest.mark.asyncio
async def test_vault_client_mock():
    client = VaultClient(vault_token="")
    token = await client.get_ephemeral_ssh_token("hpc_user")
    assert "ephemeral_mock_ssh_token_hpc_user" in token

def test_gvisor_driver_path_traversal(monkeypatch):
    driver = GVisorSandboxDriver()

    with pytest.raises(PermissionError, match="Path traversal or absolute access blocked"):
        driver.execute_python_script("../escape.py")

    with pytest.raises(PermissionError, match="Path traversal or absolute access blocked"):
        driver.execute_python_script("/absolute/path/escape.py")

    # RNF-002 regression: a Windows drive-letter path must be blocked too (the
    # old '..'/leading-slash denylist let this through).
    with pytest.raises(PermissionError, match="Path traversal or absolute access blocked"):
        driver.execute_python_script("C:\\Windows\\System32\\config\\SAM")

    # Local fallback output. Clear CI so `_execute` takes the mock branch
    # deterministically -- otherwise GitHub Actions (which sets CI=true) would run
    # a real `python correct_script.py` subprocess against a non-existent file.
    monkeypatch.delenv("CI", raising=False)
    # `execute_python_script` returns `(stdout, exit_code)`, not a bare string
    # (RF-005 gap-closure phase; see `gvisor_driver.py`).
    out, exit_code = driver.execute_python_script("correct_script.py")
    assert "Mock execution output" in out
    assert exit_code == 0

@pytest.mark.asyncio
async def test_slurm_dispatcher_mock():
    dispatcher = SlurmSSHDispatcher()
    job_id = await dispatcher.dispatch("#SBATCH --job-name=test")
    assert job_id == "job_10492"

@pytest.mark.asyncio
async def test_mcp_server_registry_route():
    # `route()` now actually consults `self.registry` instead of returning a
    # hardcoded success string for any tool name -- a handler must be
    # registered first, exactly as a real local/remote MCP server would be.
    registry = MCPServerRegistry()

    def execute_sandbox_python(arguments):
        script = arguments.get("script_content", "")
        return f"Processed script successfully: {len(script)} bytes."

    registry.register_server("execute_sandbox_python", execute_sandbox_python)

    out = await registry.route("execute_sandbox_python", {"script_content": "print('hello')"})
    assert "Processed script successfully" in out


@pytest.mark.asyncio
async def test_mcp_server_registry_route_unregistered_tool_is_explicit():
    # An unregistered tool must get a clear "not implemented" style response,
    # not a hardcoded string implying real execution happened.
    registry = MCPServerRegistry()
    out = await registry.route("some_unregistered_tool", {"arg": 1})
    assert "not registered" in out
    assert "some_unregistered_tool" in out

@pytest.mark.asyncio
async def test_btrfs_snapshot_manager_fallback():
    manager = BtrfsSnapshotManager(use_btrfs=False)
    
    # Test directory copying fallback
    source = "test_src_dir_tmp"
    target = "test_tgt_dir_tmp"
    
    os.makedirs(source, exist_ok=True)
    with open(os.path.join(source, "file.txt"), "w") as f:
        f.write("data")
        
    await manager.create_snapshot(source, target)
    
    assert os.path.exists(os.path.join(target, "file.txt"))
    
    # Clean up
    import shutil
    shutil.rmtree(source, ignore_errors=True)
    shutil.rmtree(target, ignore_errors=True)
