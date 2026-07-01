# Autenticação, Tokens Efêmeros e Rate Limiting
**ID Documento:** ARCH-API-002 | **Status:** Aprovado | **Versão:** 1.0.0

O OSW opera como uma central de processamento laboratorial sensível. Credenciais estáticas configuram vulnerabilidades inadmissíveis no manuseio de LLMs.

## 1. Gestão de Chaves de Autenticação (Zero-Trust via HashiCorp Vault)
- **O Problema:** Os prompts do Agente não podem jamais conter chaves da OpenAI, DeepSeek ou senhas de laboratório no histórico, a fim de mitigar *Prompt Leakage*.
- **A Solução:** A API Gateway injeta Credenciais Efêmeras apenas no Invoker MCP que atua como proxy. O LLM faz a requisição `get_uniprot_data`, e o MCP Host no Gateway adiciona silenciosamente o cabeçalho Bearer Token buscado do HashiCorp Vault, expirando em 5 minutos.

## 2. Rate Limiting e Fallback
O consumo do servidor REST API obedece quotas rígidas para evitar DDoS financeiro sobre a chave de API do modelo gerador (LLM) e esgotamento de servidores NCBI:
- **Rate Limit Local:** `10 req/s` no endpoint de Chat e Fork.
- **Roteamento Híbrido Caching:** Chamadas MCP idênticas (ex: dobrar 2x a mesma exata sequência FASTA) são interceptadas pela camada de Caching Semântica Local do Redis, devolvendo o `artifact_hash` prévio em 5ms em vez de lançar outra job à GPU (Economia e Bypass de Threshold de API Remota).
