# Análise de Marcos e Riscos Críticos (Milestones & Risks)
**ID Documento:** ARCH-PLAN-002 | **Status:** Aprovado | **Versão:** 1.0.0

A execução do roadmap arquitetural traz riscos subjacentes que demandam ações de controle de engenharia.

| Marco (Milestone) | Risco Técnico Primário | Probabilidade x Impacto | Plano de Mitigação Sistêmico |
| :--- | :--- | :--- | :--- |
| **M1: Sandbox IPC** | Fuga de memória (Memory Leak) em transmissões stdio longas no MCP. | Alta x Média | Implementar buffer flush estrito a cada 1MB de stdout e timeout kill na porta IPC. |
| **M2: GraphRAG** | Alta taxa de alucinação se o reranker escolher nós Graph errados da Neo4j. | Média x Crítico | Enforçar "Entity Binding" via BGE-M3 (Triplos RDF). Somente permitir citação se o ID for rígido. |
| **M3: MCTS Forking** | Latência na tentativa do modelo auto-corrigir bugs de código (Deadloops). | Alta x Alta | Impor `token_budget` severo por request. Timeout forçado no `PydanticAI` (Max_Retries = 3). |
| **M4: WebGL 3D** | Incompatibilidade e crash de navegador ao renderizar grandes complexos no Molstar. | Alta x Alta | Lógica de downsampling e LOD (Level of Detail) ativada se a malha do PDB exceder 5.000 átomos no Next.js. |
| **M5: Slurm / Cloud**| Escalamento de privilégio de rede local no login node do Slurm Cluster. | Baixa x Catastrófico | O OSW Gateway emite túnel Paramiko apenas sob escopo de usuário restrito e mTLS (Zero-Trust). |
