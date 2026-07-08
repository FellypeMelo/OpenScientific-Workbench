# Plano de Execução — Fechamento de Lacunas (Alpha → Utilizável)
**ID Documento:** ARCH-PLAN-002 | **Status:** Proposto | **Versão:** 1.0.0

Plano tático de engenharia para levar o estado atual do repositório (`0.1.0`, arquitetura madura porém infra/frontend majoritariamente em *stub*) até um backend com persistência real e um cliente funcional. Complementa o roadmap estratégico [ARCH-PLAN-001](roadmap_m01_m10.md); aqui o foco é a ordem de dependência técnica e o esforço concreto.

## Diagnóstico de maturação (base do plano)
- **Maduro:** Clean Architecture + DDD (4 entidades, 7 ports, 6 casos de uso), disciplina de testes (25 arquivos, *gate* de 80% no CI), CI/CD com E2E orquestrando Postgres/Qdrant/Redis, `docker-compose.dev.yml`.
- **Lacunas:** infra mock-pesada (Slurm/gVisor/Vault/Btrfs/Neo4j), rotas usando repositórios em memória, `middleware/` vazio, streaming de LLM com `pass`, frontend ~30% (Molstar/IGV são placeholder), sem deploy de produção.
- **Elo faltante central:** não existe camada de engine/sessão do SQLAlchemy no `src/` — os adaptadores Postgres estão prontos mas não são fiados na aplicação.

---

## Fase 0 — Higiene e fundações *(≈1 dia · desbloqueia tudo)*
1. Corrigir versão do Python no CI: `.github/workflows/ci.yml` instala 3.10, mas `backend/pyproject.toml` exige `>=3.12`. Alinhar para 3.12.
2. Módulo de configuração `src/infrastructure/config.py` com `pydantic-settings`: `DATABASE_URL`, `REDIS_URL`, `NEO4J_URI`, `QDRANT_HOST`, chaves de LLM.
3. Migrar dependências para os grupos do `pyproject` (o CI hoje reinstala pacotes manualmente em vez de `pip install .`).

## Fase 1 — Fiar Postgres na aplicação ⭐ *(≈2–3 dias · maior impacto)*
Transforma o backend de "mock em memória" para persistência real.
1. `src/infrastructure/persistence/database.py`: `create_async_engine` + `async_sessionmaker` + dependência `get_db_session()`.
2. `src/presentation/dependencies.py`: providers de repositório via `Depends(get_db_session)`.
3. Refatorar `routes/sessions.py` e `routes/chat.py` para injetar `PostgresSessionRepository`/`PostgresWorkspaceRepository`, removendo os mocks de módulo (sessions.py linhas 13–20).
4. `lifespan` em `presentation/main.py` para criar/encerrar o engine e rodar `Base.metadata.create_all` (ou introduzir **Alembic** para migrações).
5. Estender testes de integração para bater nas rotas fiadas via `TestClient` + DB de teste.

## Fase 2 — Middleware de segurança real *(≈2–3 dias)*
O diretório `src/presentation/middleware/` só tem `__init__.py` vazio apesar do commit de "JWT/limits".
1. Middleware de autenticação JWT (validação de claims / `iam_role`).
2. Rate limiting (Redis já disponível no compose).
3. Security headers. Registrar em `main.py` + testes.

## Fase 3 — Streaming de LLM *(≈2 dias)*
1. Implementar `generate_stream` nos 4 provedores em `infrastructure/llm/model_client_factory.py` (hoje `pass` nas linhas 60/90/118).
2. Ligar o SSE token-a-token em `routes/chat.py`, substituindo o mock atual.

## Fase 4 — Adaptadores de infra reais *(≈2–3 semanas)*
Trocar mocks por integração real: Slurm via paramiko (hoje retorna `job_10492` fixo), execução gVisor/runsc, cliente Vault, snapshots Btrfs (CoW), GraphRAG no Neo4j.

## Fase 5 — Completar o frontend *(≈2–3 semanas)*
Integrar Molstar (proteína 3D) e IGV (genômica) — hoje `<div>` placeholder em `frontend/src/app/page.tsx` —, camada de cliente de API, gerência de estado e fluxo de login.

## Fase 6 — Deploy de produção *(≈1 semana)*
Dockerfiles (backend/frontend) + manifestos K8s/Helm. Inexistente hoje.

---

## Recomendação de sequência
Iniciar por **Fase 0 + Fase 1** juntas: baixo esforço, convertem o protótipo em backend com persistência real e destravam as fases seguintes. Cada fase deve manter o *gate* de 80% de cobertura verde antes do merge.
