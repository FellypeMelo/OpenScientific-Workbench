# Matriz de Rastreabilidade (Traceability Matrix)
**ID Documento:** REQ-TRC-001 | **Status:** Aprovado | **Versão:** 1.0.0

A Matriz de Rastreabilidade garante que todos os Requisitos Funcionais (RF) e Requisitos Não Funcionais (RNF) do OpenScientific-Workbench (OSW) estão devidamente alinhados aos componentes da Arquitetura e casos de teste associados, atendendo à conformidade técnica do `REGREQ-009`.

| ID Requisito | Título / Descrição Resumida | Componente de Arquitetura Alvo | Caso de Teste Referenciado |
| :--- | :--- | :--- | :--- |
| **RF-001** | Coordenação via MCTS PydanticAI | Backend Core: Pydantic Orchestrator | `TEST-INT-010` (Teste MCTS DAG) |
| **RF-002** | Agente Revisor Crítico (Actor-Critic) | Gateway de Roteamento MCP | `TEST-UNIT-045` (Validador de Desvio Matemático < 1e-5) |
| **RF-003** | Persistência de Estado (Working Memory) | Camada de Dados: PostgreSQL JSONB | `TEST-UNIT-021` (Sincronismo Checkpoint) |
| **RF-004** | MCP Universal e Conectores BD (UniProt/PDB) | Servidores MCP Remotos (BioContextAI) | `TEST-INT-080` (Fetch MCPmed via JWT) |
| **RF-005** | Execução Rootless gVisor | Docker Sandbox (Local) | `TEST-SEC-002` (Fuga de Privilégio Rootless) |
| **RF-006** | Integração HPC Slurm via Paramiko SSH | Distribution: Celery Worker HPC | `TEST-INT-110` (Submissão SSH sbatch e mock Squeue) |
| **RF-007** | Visualização Nativa Molstar / IGV.js | Camada de Apresentação (Next.js) | `TEST-E2E-005` (Renderização de PDB via UI) |
| **RF-008** | Editor de Manuscrito Interativo (Tectonic) | Camada de Apresentação | `TEST-E2E-012` (Geração de PDF via Texto e Revisão) |
| **RF-009** | Instalação Semântica de Skill (skill-to-mcp) | Registro de Skills/Conectores | `TEST-UNIT-033` (Parser YAML Frontmatter SKILL) |
| **RNF-001** | Segurança Namespace Isolado (gVisor) | Auditor de Segurança / Sandbox | `TEST-SEC-015` (Syscall Hooking Negativo) |
| **RNF-002** | Mitigação Path Traversal CVE-2026-7398 | Orquestrador Central / File Manager | `TEST-SEC-018` (Payload ../../etc/passwd) |
| **RNF-003** | IAM Token e Credenciais Efêmeras (Vault) | API Gateway | `TEST-SEC-022` (Expiração Token Rápida) |
| **RNF-006** | Reprodutibilidade com SHA-256 (uv.lock) | Gestor de Estado / Snapshot ZFS | `TEST-UNIT-090` (Check Hash Locking) |
| **RNF-007** | Snapshots File System (CoW Forking) | Container OS Host Filesystem | `TEST-INT-101` (Criação de Fork de 1ms de Workspace Btrfs) |
