# Alocação de Equipe e Esforço (Team Allocation)
**ID Documento:** ARCH-PLAN-003 | **Status:** Aprovado | **Versão:** 1.0.0

Estimativas de dimensionamento da engenharia de software baseado em COCOMO II, com time multidisciplinar sênior para as 5 Fases do OSW.

## Composição Padrão Sugerida (Squad OSW Core)
1. **Tech Lead / AI Architect (1x):** Design do DAG PydanticAI, MCP Protocol e Arquitetura Vault.
2. **Engenheiros Backend / Python (2x):** Implementação da API Gateway FastAPI, Revisor Crítico e Integrações Neo4j/Qdrant.
3. **Engenheiros Frontend (2x):** UI em Next.js, integrações WebSocket e wrappers para WebComponents Molstar/IGV.js.
4. **Cientista de Dados / Bioinformata (2x):** Extração de GraphRAG, Validação Algorítmica e configuração do SKILL.md.
5. **Site Reliability Engineer - SRE/Security (1x):** Provisionamento de Kubernetes/Docker Rootless, gVisor, Túnel SSH Paramiko Slurm, e Observabilidade OTel.

## Esforço Cumulativo
- A equipe transita de 3 Engenheiros na Fase 1 para o pico de 6 a 8 Engenheiros nas Fases 4 e 5 (onde há gargalo gráfico WebGL e segurança HPC acopladas).
- **Esforço Total Estimado:** ~50 a 60 Homens-Mês para a prontidão total em nível enterprise de Produção do OSW.
