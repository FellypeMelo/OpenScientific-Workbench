# C4 Modelo Nível 1: Contexto de Sistema
**ID Documento:** ARCH-C4-L1 | **Status:** Aprovado | **Versão:** 1.0.0

Este diagrama mapeia os limites sistêmicos e as interações do Cientista com os ecossistemas HPC e bases de dados externas utilizando o OSW.

```mermaid
C4Context
    title Diagrama de Contexto de Sistema (Nível 1) - OSW

    Person(scientist, "Cientista / Bioinformata", "Usuário que formula as hipóteses científicas e solicita simulações computacionais em linguagem natural.")

    System_Boundary(osw_boundary, "OpenScientific-Workbench (OSW)") {
        System(osw_system, "OSW Core", "Orquestrador de Agentes de IA e ambiente unificado para análise molecular e genômica isolada.")
    }

    System_Ext(bio_databases, "Bases de Dados Biológicas", "UniProt, PDB, STRING, ClinVar fornecidas via BioContextAI (MCPmed).")
    System_Ext(hpc_cluster, "HPC / Slurm Cluster", "Infraestrutura corporativa ou institucional provendo GPUs para predições pesadas (Boltz-2).")
    System_Ext(modal_cloud, "Modal Cloud", "Provedor serverless de GPU on-demand para escalonamento rápido.")

    Rel(scientist, osw_system, "Submete tarefas e visualiza renderizações WebGL")
    Rel(osw_system, bio_databases, "Busca conhecimentos e metadados científicos via MCP HTTPS", "JSON-RPC")
    Rel(osw_system, hpc_cluster, "Despacha scripts de execução (Sbatch)", "SSH / mTLS")
    Rel(osw_system, modal_cloud, "Lança funções serverless de alto desempenho", "REST API")
```
