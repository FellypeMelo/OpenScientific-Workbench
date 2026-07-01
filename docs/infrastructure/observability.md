# Observabilidade (Observability)
**ID Documento:** ARCH-INF-003 | **Status:** Aprovado | **Versão:** 1.0.0

Um sistema que interage com um LLM para gerar códigos (Agentic System) opaco, rapidamente torna-se uma caixa-preta laboratorial. O OSW integra o **OpenTelemetry (OTel)** no núcleo para exposição ativa de telemetria (Tracing, Metrics e Logs).

## 1. Instrumentação de Tracing Distribuído
Cada comando natural do usuário abre um **Trace ID** único. O PydanticAI está envolto (wrapped) com spans OTel que propagam esse Contexto:
- `Span 1`: Ingestão do RAG no Neo4j (Tempo Gasto).
- `Span 2`: Invocação MCP (Latência HTTP remota ao BioContextAI).
- `Span 3`: Execução Física no Sandbox gVisor (stdout stderr capturados como Log Records).

## 2. Monitorização e Painel (Jaeger & Prometheus)
- **Jaeger Collector:** Roteia e exibe visualmente os Spans (Tracing) no painel integrado do OSW. Fundamental para descobrir onde ocorreu divergência térmica ou timeout de VRAM de um LLM que tentou invocar Evo 2.
- **Prometheus Metrics:** O OSW contabiliza estritamente os **Tokens Consumidos** (Input/Output). Há thresholds fixos para evitar a bancarrota de créditos de API em LLMs comerciais na eventualidade de uso de fallback models em tarefas pesadas.
