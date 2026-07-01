# Especificação de Interface de Ferramentas (OpenAPI / MCP)
**ID Documento:** ARCH-API-001 | **Status:** Aprovado | **Versão:** 1.0.0

A integração com as Ferramentas e a comunicação entre o LLM Core e o OSW seguem a especificação híbrida OpenAPI 3.1 e **Model Context Protocol (MCP)** via JSON-RPC 2.0.

## 1. Especificação MCP (JSON-RPC)
Todo comando de execução biológica deve obedecer à listagem estrita de ferramentas devolvida pelo servidor (via STDIO no Docker ou HTTP local).

### 1.1 Invocação da Ferramenta de Sandbox Python
```json
{
  "jsonrpc": "2.0",
  "id": "call_12345",
  "method": "tools/call",
  "params": {
    "name": "execute_sandbox_python",
    "arguments": {
      "script_content": "import scanpy as sc\nadata = sc.read_h5ad('workspace/data.h5ad')\n...",
      "timeout_sec": 300
    }
  }
}
```
**Regra de Isolamento:** O servidor MCP host interceptará `script_content`, o despejará num arquivo efêmero temporário (UUID) e invocará `runsc` (gVisor) apontando para esse arquivo.

## 2. API Gateway REST (UI para Orquestrador)
A Interface de Usuário (Next.js) comunica-se via FastAPI sob endpoints OpenAPI.
- `POST /api/v1/sessions` -> Inicializa estado persistente.
- `POST /api/v1/sessions/{id}/chat` -> Submissão em NL que engatilha o MCTS e o Agente Coordenador.
- `GET /api/v1/sessions/{id}/stream` -> Server-Sent Events (SSE) retornando Spans de log em tempo real (ex: "Validação num. concluída - 0 falhas").
