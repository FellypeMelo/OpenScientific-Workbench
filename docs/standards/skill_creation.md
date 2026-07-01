# Criação e Empacotamento de Skills Científicas
**ID Documento:** ARCH-STD-002 | **Status:** Aprovado | **Versão:** 1.0.0

A extensibilidade do OSW reside na capacidade dos pesquisadores acoplarem novas ferramentas de análise biológica ou química à interface unificada, via formato padrão de empacotamento.

## Estrutura Obrigatória de um Diretório Skill

Cada competência adicionada na pasta raiz `skills/` DEVE conter:

1. **O arquivo `SKILL.md`:** 
   O frontmatter YAML é obrigatório e será convertido automaticamente pela biblioteca `skill-to-mcp` para prover ao LLM a descrição detalhada do JSON-Schema dos parâmetros de entrada e saída, incluindo limites e tipagens estritas. Exemplo: `min_genes: type: integer, default: 200`.

2. **Diretório `references/`:** 
   Limites de qualidade e *thresholds*. Informações teóricas estáticas de biologia usadas apenas pelo Agente Revisor para cruzar dados. (Exemplo: "Na análise x, se a variância for > Y, marque como ruidoso").

3. **Arquivo de Bloqueio (`environment.yaml` / `uv.lock`):** 
   Garantia da reprodutibilidade. Sem isso, o Skill não compilará dentro do gVisor Sandbox e falhará no linting.
