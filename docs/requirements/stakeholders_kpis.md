# Stakeholders e KPIs
**ID Documento:** REQ-STK-001 | **Status:** Aprovado | **Versão:** 1.0.0

## 1. Perfil dos Stakeholders

| Stakeholder | Papel | Expectativas / Interesses Primários |
| :--- | :--- | :--- |
| **Cientista Principal (PI)** | Usuário Final | Redução de custos computacionais (meta: 85%), validações científicas precisas (sem alucinações), garantia de reprodutibilidade total. |
| **Engenheiro de Bioinformática** | Criador de Habilidades (Skills) | Extensibilidade da plataforma via formato aberto (SKILL.md), integração rápida de pacotes Conda/uv. |
| **CTO / SysAdmin HPC** | Operador de Infraestrutura | Segurança local da rede e cluster, isolamento de recursos via containers gVisor, monitoramento de GPU via telemetria. |
| **Oficial de Segurança (CISO)** | Auditor / Conformidade | Adequação LGPD/GDPR, proteção de PII de genomas, modelagem STRIDE, isolamento criptográfico do Vault. |

## 2. Indicadores Chave de Performance (KPIs)

| ID KPI | Nome do Indicador | Métrica Alvo (Threshold) | Propósito de Acompanhamento |
| :--- | :--- | :--- | :--- |
| **KPI-01** | Redução de Custo de LLM Comercial | > 85% vs. APIs Comerciais (ex. Claude 3.5 Sonnet) | Garantir que o uso de modelos abertos no OSW mantém viabilidade financeira para long-running tasks. |
| **KPI-02** | Confiança de Verificação Crítica | 100% dos relatórios (Erro Absoluto < 1e-5) | O Revisor Crítico deve detectar desvios numéricos em toda interação. |
| **KPI-03** | Consumo de Contexto (Tokens) | < 30% do teto máximo por sub-agente | Evitar gargalos no LLM host através de delegação semântica distribuída. |
| **KPI-04** | Carga Térmica/OOM de GPU | Taxa de falhas de memória < 5% | Monitorar orquestração remota para evitar interrupções severas de predição molecular (Modal/Slurm). |
| **KPI-05** | Latência MCP RTT | < 1.5 Segundos por requisição HTTP | Garantir fluidez e usabilidade contínua da IU para o usuário investigador. |
