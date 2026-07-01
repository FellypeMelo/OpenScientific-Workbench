# ADR 001: Orquestração Multi-Agente Baseada em Grafos (MCTS)
**ID:** ADR-001 | **Status:** Aprovado | **Autor:** Arquiteto Principal

## 1. Contexto e Problema
Pipelines de pesquisa biológica (ex: setup de simulações com Evo 2) não são lineares. LLMs encadeados por "chat linear" (padrão AutoGen) tendem a ficar em loops infinitos ou gerar alucinações cumulativas (o erro da etapa 1 quebra a etapa 10). Precisamos de um orquestrador que faça "backtracking" inteligente.

## 2. Alternativas Avaliadas
- **A)** LangGraph (Linear state machine).
- **B)** CrewAI (Agentes hierárquicos sem formal validation).
- **C)** **PydanticAI com Agentic Tree Search (MCTS)**.

## 3. Decisão
Optou-se pela **Alternativa C (PydanticAI + MCTS)**. O Orquestrador será um interpretador de grafos dinâmicos onde o Revisor atua como função de "recompensa" no Monte Carlo Tree Search, podando (cancelando) ramos de código que falhem sintaticamente na Sandbox antes de propagar falhas.

## 4. Consequências (Trade-offs)
- **Positivo:** Redução de falhas (alucinações) e altíssima taxa de sucesso em pipelines longos (dias). Prevenção de loop infinito.
- **Negativo:** Elevada complexidade de implementação (DAG stateful persistido no PostgreSQL). Requer desenvolvedores familiarizados com Teoria dos Grafos.
