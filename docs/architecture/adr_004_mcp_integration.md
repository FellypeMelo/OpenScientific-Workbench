# ADR 004: Arquitetura de Conectores via Protocolo MCP
**ID:** ADR-004 | **Status:** Aprovado | **Autor:** Tech Lead

## 1. Contexto e Problema
Como o Orquestrador PydanticAI (LLM) buscará proteínas no UniProt, renderizará PDBs ou invocará algoritmos sem escrever centenas de integrações de API hardcoded e difíceis de manter?

## 2. Alternativas Avaliadas
- **A)** Plugins LangChain Customizados (Forte acoplamento ao framework em Python).
- **B)** Funções REST Tool Call Nativas da OpenAI (Prende o OSW a provedores específicos).
- **C)** **Model Context Protocol (MCP)**.

## 3. Decisão
O padrão arquitetural oficial do OSW é o **MCP (Anthropic/Open Source)**. Todo recurso científico e base de dados externa será acessado via servidores MCP. Integraremos nativamente com o consórcio **BioContextAI / MCPmed**.

## 4. Consequências
- **Positivo:** Desacoplamento extremo. O motor LLM do OSW não sabe o que é o UniProt, apenas conhece uma Ferramenta MCP "get_uniprot_sequence". Facilita a portabilidade entre DeepSeek, Llama3 ou Qwen.
- **Negativo:** Necessidade de rodar instâncias de Servidores MCP lado a lado com a aplicação via stdio ou HTTP SSE.
