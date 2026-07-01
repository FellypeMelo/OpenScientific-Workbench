# Catálogo de Erros de Tarefas Biológicas
**ID Documento:** ARCH-API-003 | **Status:** Aprovado | **Versão:** 1.0.0

Quando o MCP Server ou as sub-tarefas da sandbox falham, um código de erro tipado é devolvido via JSON-RPC. O Agente Coordenador MCTS lê este código para planejar automaticamente a "Transaction Compensatória" (Auto-correção) ou abortar o ramo de busca.

## Erros Operacionais (Auto-Recuperáveis)
| Código MCP | Alias de Domínio | Significado e Disparo de Correção (Actor-Critic) |
| :--- | :--- | :--- |
| **`4001`** | `ERR_PATH_TRAVERSAL_BLOCK` | Agente tentou salvar arquivo fora do diretório `/workspace`. Coordenador reprompta o agente exigindo caminhos relativos na raiz. |
| **`4002`** | `ERR_NUMERIC_DIVERGENCE` | Agente Revisor encontrou erro absoluto > `1e-5` no manuscrito vs arquivo `.csv`. Coordenador emenda os valores textuais falsos gerados. |
| **`4003`** | `ERR_TIMEOUT_VRAM_OOM` | Simulação Evo 2 ou Boltz-2 causou falta de VRAM (Out of Memory). Coordenador reescalona a requisição via mTLS para o Modal Cloud ou Slurm Remote GPU. |

## Erros Fatais (Abortar DAG / Cancelar Missão)
| Código MCP | Alias de Domínio | Ação de Isolamento |
| :--- | :--- | :--- |
| **`5001`** | `FATAL_GVISOR_SYSCALL_HOOK` | Processo Python tentou ler `/etc/passwd`. Sandbox é destruída fisicamente, a sessão abortada e alerta SIEM enviado. |
| **`5002`** | `FATAL_LLM_BUDGET_EXCEEDED` | O Agente iterou 50 vezes sem resolver uma dependência do Conda-Forge, esgotando o limite de tokens da sessão. Intervenção humana requerida. |
