# Roadmap de Implementação (Meses 01 a 10)
**ID Documento:** ARCH-PLAN-001 | **Status:** Aprovado | **Versão:** 1.0.0

A entrega do OSW segue o plano estruturado em 5 grandes marcos sequenciais para reduzir o Time-To-Market em laboratórios de ponta.

## Fase 1 — MVP (Mês 1-2)
- **Objetivos:** Interface básica (Next.js), contentor seguro (`Docker rootless + gVisor`) e interpretadores Python via chamadas MCP.
- **Entregável Chave:** Chat executando scripts `Python` ou `R` confinados isoladamente com sucesso na porta local.

## Fase 2 — Assistente de Investigação (Mês 3-4)
- **Objetivos:** Motor de RAG Científico Baseado em Grafos e parser de arquivos `Marker`.
- **Entregável Chave:** Upload de PDF da Nature/Science via UI -> Extração RAG -> Pesquisa conversacional precisa.

## Fase 3 — Plataforma Multi-Agente (Mês 5-6)
- **Objetivos:** Orquestração dinâmica via `PydanticAI`, `MCTS` (Agentic Search) e Forking `Btrfs`.
- **Entregável Chave:** Resolução autônoma de falhas e ramificação O(1) com cliques no Histórico de Bate-Papo.

## Fase 4 — Workbench Científico (Mês 7-8)
- **Objetivos:** WebComponents visuais (`Molstar` e `IGV.js`) e Motor de Skills (`SKILL.md`).
- **Entregável Chave:** LLM alterando renderização 3D de proteínas na tela automaticamente após as simulações.

## Fase 5 — Cluster de Produção (Mês 9-10)
- **Objetivos:** Despacho remoto para clusters Slurm institucionais via túnel mTLS SSH e chaves temporárias via Vault.
- **Entregável Chave:** Agente capaz de submeter `Boltz-2` em GPUs remotas (Slurm/Modal) com monitoramento e resgate de resultado automático.
