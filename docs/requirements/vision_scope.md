# Visão do Produto e Escopo (Vision & Scope)
**ID Documento:** REQ-VS-001 | **Status:** Aprovado | **Versão:** 1.0.0

## 1. Visão do Produto
O **OpenScientific-Workbench (OSW)** tem a visão de fornecer a alternativa de código aberto mais robusta e segura ao *Claude Science*. O produto atua como um sistema integrado (Client-Server) para pesquisadores, onde tarefas complexas de laboratório e bioinformática são convertidas em abstrações semânticas e executadas autonomamente através de LLMs e protocolos MCP em ambientes fechados.

O sistema elimina o atrito inerente à manipulação de bibliotecas científicas distintas, orquestrando bases de conhecimento (UniProt, PDB), frameworks quantitativos, interfaces gráficas tridimensionais, e Clusters HPC a partir de um comando central em linguagem natural.

## 2. Escopo Incluído (In-Scope)
- Interfaces visuais embarcadas no navegador para observação tridimensional (WebGL Molstar).
- Agente Coordenador (LLM local ou remoto) que planeja sub-tarefas por MCTS (Monte Carlo Tree Search).
- Agente Revisor Crítico responsável pela validação algorítmica de consistência em CSV/Tabelas e detecção de alucinações.
- Suporte a infraestrutura local (Docker Rootless + gVisor).
- Despacho de tarefas remotas por SSH Paramiko (Slurm HPC) ou APIs de Cloud (Modal).
- Sistema File-system Snapshotting Copy-on-Write (CoW) para bifurcações de pesquisa (Forking).
- Implementação de rastreabilidade (Proveniência Criptográfica e UV Lockfiles).

## 3. Escopo Excluído (Out-of-Scope)
- Provimento de banco de dados genômico nativo (os dados devem ser acessados no BioContextAI/MCPmed ou bases de terceiros).
- Suporte a ambientes Windows nativos sem WSL2 / Containers Linux.
- Execução não-supervisorada de scripts arbitrários (Toda operação passa por auditoria e gVisor).
