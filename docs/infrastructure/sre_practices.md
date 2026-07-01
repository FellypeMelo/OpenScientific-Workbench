# Práticas SRE (Site Reliability Engineering)
**ID Documento:** ARCH-INF-004 | **Status:** Aprovado | **Versão:** 1.0.0

Adoção de métodos quantitativos em SRE para balizar a confiabilidade do Workflow Computacional de HPC do OSW.

## 1. SLI (Service Level Indicators) e SLO (Service Level Objectives)

| Componente | SLI Métrica de Qualidade | SLO (Alvo Desejado) | Ação Reativa de SRE |
| :--- | :--- | :--- | :--- |
| **API Gateway OSW** | Taxa de falhas `5xx` na porta 8000. | **99.9%** (Erros < 0.1%) | Rollback automático de build. Investigar memory leak da UI. |
| **Revisor Crítico (Actor)** | Fração de relatórios com "Alucinação Numérica" gerando Retentativa MCTS. | **< 15%** dos prompts | Refinar System Prompts de base se a taxa de regressões do LLM exceder este teto, ajustando temperaturas. |
| **HPC Dispatch** | Tempo para obter aprovação Vault Token e empacotar payload Sbatch (.sh). | **< 3 segundos** (p95) | Aumentar réplicas do módulo Dispatcher Celery. |
| **Sandbox CoW (Btrfs)**| Latência do comando de `Snapshot/Fork` em diretórios grandes (50GB+). | **< 1 segundo** (p99) | Manutenção de Filesystem: acionar balance/defrag no S.O. host. |

## 2. Detecção Preditiva de Anomalias e Circuit Breakers
- **Circuit Breaker HPC:** Caso a fila Squeue do Slurm remoto não responda por 15 segundos ou reporte *Thermal Throttling* (Divergência Térmica) excessiva nos nós de GPU rodando Boltz-2, a ponte Slurm REST Client do OSW ativa estado `OPEN` falhando as chamadas rapidamente, retornando um erro `4003` para o Orquestrador repensar o plano sem onerar mais as placas do laboratório.
