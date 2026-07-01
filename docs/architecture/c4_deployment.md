# C4 Modelo Nível 4: Implantação (Deployment)
**ID Documento:** ARCH-C4-L4 | **Status:** Aprovado | **Versão:** 1.0.0

Exibe o mapeamento do software sobre as infraestruturas físicas na topologia de um laboratório de biologia padrão (On-Premises).

```mermaid
C4Deployment
    title Diagrama de Implantação (Nível 4) - Topologia de Laboratório OSW

    Deployment_Node(local_ws, "Workstation do Pesquisador", "Linux Desktop") {
        Deployment_Node(browser, "Web Browser", "Chromium/Firefox") {
            Container(spa_ui, "Interface Next.js / Molstar")
        }
        
        Deployment_Node(docker_daemon, "Docker Engine Rootless", "Namespace Isolado") {
            Container(api_gateway, "Orquestrador FastAPI")
            Container(db_stack, "PostgreSQL + Neo4j + Qdrant")
            Deployment_Node(gvisor_runtime, "gVisor (runsc)", "Kernel Isolado") {
                Container(sandbox_env, "OSW Secure Sandbox (Python/R)")
            }
        }
        
        Deployment_Node(storage, "ZFS / Btrfs Pool", "NVMe") {
             System(workspace_fs, "OSW Workspace Mount (Copy-on-Write)")
        }
    }

    Deployment_Node(hpc_dc, "Datacenter Institucional", "On-Premise Network") {
        Deployment_Node(slurm_login, "Slurm Login Node", "CentOS/Ubuntu") {
             System(ssh_receiver, "SSH Receiver & Slurm CLI")
        }
        Deployment_Node(gpu_nodes, "Nós Computacionais GPU", "A100/H100") {
             System(boltz2, "Boltz-2 / Evo 2 Workers")
        }
    }

    Rel(spa_ui, api_gateway, "wss://localhost:8000")
    Rel(api_gateway, sandbox_env, "STDIO IPC")
    Rel(sandbox_env, workspace_fs, "Volume Mount (Restrito)", "rw")
    Rel(api_gateway, ssh_receiver, "Envia .sh Sbatch", "mTLS / SSH Tunnel")
    Rel(ssh_receiver, boltz2, "Aloca recursos GPU (sbatch)")
```
