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

def test_gvisor_driver_path_traversal():
    driver = GVisorSandboxDriver()
    
    with pytest.raises(PermissionError, match="Path traversal or absolute access blocked"):
        driver.execute_python_script("../escape.py")
        
    with pytest.raises(PermissionError, match="Path traversal or absolute access blocked"):
        driver.execute_python_script("/absolute/path/escape.py")

    # Local fallback output
    out = driver.execute_python_script("correct_script.py")
    assert "Mock execution output" in out

@pytest.mark.asyncio
async def test_slurm_dispatcher_mock():
    dispatcher = SlurmSSHDispatcher()
    job_id = await dispatcher.dispatch("#SBATCH --job-name=test")
    assert job_id == "job_10492"

@pytest.mark.asyncio
async def test_mcp_server_registry_route():
    registry = MCPServerRegistry()
    out = await registry.route("execute_sandbox_python", {"script_content": "print('hello')"})
    assert "Processed script successfully" in out

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
