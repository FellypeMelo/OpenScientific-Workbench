# Visão Geral da Arquitetura (Architecture Overview)
**ID Documento:** ARCH-OV-001 | **Status:** Aprovado | **Versão:** 1.0.0

A arquitetura do OpenScientific-Workbench (OSW) é estruturada em torno de um paradigma Client-Server nativamente desacoplado que prioriza o isolamento de ambientes e segurança proativa (Zero-Trust). 

O OSW adota o padrão **Model Context Protocol (MCP)** como sua espinha dorsal, separando o raciocínio semântico de longo contexto executado pelos Foundation Models (DeepSeek-V3 / Qwen) das chamadas e execuções quantitativas em Python/R executadas dentro do Sandbox local (`gVisor`) ou em instâncias remotas (Slurm HPC).

A estrutura é dividida fundamentalmente em quatro grandes camadas C4:
1. **Camada de Apresentação (UI):** Interfaces em Next.js renderizando visualizadores WebGL (Molstar, IGV.js).
2. **Orquestrador Central:** Core FastAPI + PydanticAI interpretando intenções, desenhando Grafos DAG e atuando via Agente Coordenador e Agente Revisor.
3. **Ambiente Computacional:** Conteinerização rootless segura com monitoramento de proveniência por Lockfiles (`uv.lock`) e Snapshots de Filesystem `Btrfs/ZFS`.
4. **Camadas de Infra HPC e Remoto:** Despachos de filas long-running (Celery/Slurm) para processamento em GPU remoto (Evo 2 / Boltz-2).
