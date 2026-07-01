# C4 Modelo Nível 2: Containers
**ID Documento:** ARCH-C4-L2 | **Status:** Aprovado | **Versão:** 1.0.0

Detalha os principais aplicativos e unidades de execução em contêiner dentro do limite do sistema OSW.

```mermaid
C4Container
    title Diagrama de Container (Nível 2) - OSW

    Person(scientist, "Cientista")

    System_Boundary(osw_system, "OSW Core") {
        Container(spa_ui, "Interface Web (UI)", "Next.js / TypeScript", "Painel interativo, renderizador Molstar 3D, chat interativo de submissão.")
        Container(api_gateway, "Orquestrador & API Gateway", "FastAPI / Python", "Gerenciamento de sessão, PydanticAI Multi-Agente (Revisor + Coordenador).")
        Container(sandbox_env, "Sandbox Segura (gVisor)", "Docker / runsc", "Execução interpretada isolada de R e Python, com privilégio restrito.")
        
        ContainerDb(db_session, "Memória de Sessão", "PostgreSQL JSONB", "Grava persistência do grafo de mensagens, sessões e históricos semânticos.")
        ContainerDb(db_vector, "GraphRAG Database", "Neo4j / Qdrant", "Armazenamento híbrido de embeddings e Triplos RDF de ontologia médica.")
    }

    Rel(scientist, spa_ui, "Acessa via HTTPS / WebSockets")
    Rel(spa_ui, api_gateway, "Consome API REST, streaming SSE", "JSON/HTTP")
    Rel(api_gateway, db_session, "Lê/Escreve checkpoins de MCTS", "TCP/5432")
    Rel(api_gateway, db_vector, "Recupera RAG Científico no Graph", "TCP/7687")
    Rel(api_gateway, sandbox_env, "Comunicação STDIO canalizada via MCP", "STDIO IPC")
```
