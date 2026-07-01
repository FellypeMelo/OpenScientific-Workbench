# Contextos Delimitados (Bounded Contexts)
**ID Documento:** ARCH-MOD-001 | **Status:** Aprovado | **Versão:** 1.0.0

A arquitetura orientada a domínio (DDD) do OSW está organizada nos seguintes **Bounded Contexts**:

## 1. Contexto de Submissão e Coordenação (Submission & Coordination Context)
- **Fronteira:** Recebe o input do Cientista e atua como API Gateway e Planejador.
- **Linguagem Ubíqua:** `Workflow`, `DAG (Directed Acyclic Graph)`, `MCTS`, `Prompt`, `Token Budget`.
- **Comunicação:** JSON-RPC (HTTP) com a UI; emite comandos assíncronos para o Contexto de Execução.

## 2. Contexto de Execução Segura (Secure Sandbox Context)
- **Fronteira:** Isolação gVisor e execução rootless local.
- **Linguagem Ubíqua:** `Sandbox`, `Syscall`, `Mount`, `Path Traversal`, `Workspace`, `Lockfile`.
- **Comunicação:** Recebe submissões restritas via STDIO, sem acesso à internet externa.

## 3. Contexto de Revisão Científica (Scientific Review Context)
- **Fronteira:** O Agente Revisor Ator-Crítico.
- **Linguagem Ubíqua:** `Threshold`, `Erro Absoluto (<1e-5)`, `Asserção Numérica`, `Alucinação`, `Citação`.
- **Comunicação:** Valida o Output do Sandbox Context antes de liberar ao Coordination Context.

## 4. Contexto de Integração e HPC (Integration & HPC Context)
- **Fronteira:** Conectores BioContextAI e Túneis SSH Slurm.
- **Linguagem Ubíqua:** `MCP Server`, `BioCypher`, `Sbatch`, `GPU Node`, `Squeue`.
- **Comunicação:** Roteamento MUX, HTTPS/mTLS.
