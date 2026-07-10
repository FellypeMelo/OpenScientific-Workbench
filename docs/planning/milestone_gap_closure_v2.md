# Milestone — Gap Closure v2 (Auditoria Real vs. Proposto)
**ID Documento:** ARCH-PLAN-003 | **Status:** Em execução | **Versão:** 2.0.0
**Data:** 2026-07-10 | **Base:** auditoria por requisito contra código real (17 requisitos, 19 agentes) + suite (`122 passed`, Python 3.10 local / CI 3.12)

Este documento substitui a leitura otimista do `validation_checklist.md` ("48/48 ✔️") por um diagnóstico honesto: **os blocos isolados são reais e testados, mas a orquestração agêntica de ponta-a-ponta não existe.** Todo item abaixo tem evidência de arquivo.

---

## 1. O que o projeto se propõe (escopo)

**Requisitos Funcionais** (`docs/requirements/functional_reqs.md`): RF-001 MCTS/PydanticAI→DAG · RF-002 Ator-Crítico (<1e-5) · RF-003 Persistência JSONB · RF-004 MCP UniProt/PDB/STRING · RF-005 Sandbox gVisor · RF-006 HPC Slurm/Paramiko · RF-007 Molstar/IGV · RF-008 Editor manuscrito LaTeX/Tectonic · RF-009 SKILL.md→mcp.

**Requisitos Não-Funcionais**: RNF-001 isolamento gVisor · RNF-002 path traversal · RNF-003 Vault efêmero · RNF-004 OTel spans sandbox · RNF-005 sanitização PII · RNF-006 repro SHA-256 · RNF-007 fork CoW Btrfs · RNF-008 escala Evo2/VRAM. Roadmap adiciona RAG Grafo + parser Marker (Fase 2).

---

## 2. Feito de verdade (blocos reais, testados)

| Bloco | Arquivo | Nota |
| :--- | :--- | :--- |
| `NumericValidator` + `AuditArtifactUseCase` | `domain/services/numeric_validator.py` | `math.isclose(1e-5)` escalar + recursivo. Real. **Não fiado no pipeline.** |
| `PostgresSessionRepository` + DI | `infrastructure/persistence/` | CRUD async SQLAlchemy real, fiado nas rotas. Falta JSONB/GIN e teste em Postgres real. |
| `SlurmSSHDispatcher.dispatch()` | `infrastructure/hpc/slurm_dispatcher.py` | paramiko SSH `sbatch` + parse job-id real; fallback mock explícito. Só `dispatch()`. |
| `VaultClient.get_ephemeral_ssh_token()` | `infrastructure/security/vault_client.py` | hvac OTP real, nunca loga token. **Não fiado no Slurm.** |
| `Neo4jGraphClient` | `infrastructure/graph/neo4j_client.py` | driver async, MERGE/MATCH, injection-safe. **Dead code** (nenhum caller). |
| `BtrfsSnapshotManager` + `ForkWorkspaceUseCase` | `infrastructure/storage/btrfs_manager.py` | `btrfs subvolume snapshot` real + fallback `copytree` testado. |
| `MolstarViewer`/`IGVViewer` | `frontend/src/components/` | Mol*/igv.js reais, SSR-safe. **Dados demo fixos** (1CRN/hg38 MYC). |
| LLM streaming BYOK (4 provedores) | `infrastructure/llm/model_client_factory.py` | SSE token-a-token real (OpenAI-compat + Anthropic), verificado contra docs. |
| OTel HTTP auto-instrument | `infrastructure/telemetry.py` | TracerProvider + FastAPIInstrumentor real (genérico, não sandbox). |
| Guards path traversal | `sandbox/gvisor_driver.py`, `entities/workspace.py` | denylist testada, **mais fraca que basename** + bypass drive-letter Windows. |

---

## 3. Lacunas por requisito (veredito + evidência)

| Req | Veredito | Local? | Lacuna central |
| :--- | :--- | :--- | :--- |
| **RF-001** | 🔴 stub | parcial | `submit_task` = 4 `transition_to` lineares; `dag_snapshot` hardcoded; `pydantic-ai` dependência nunca importada; sem busca/reward/backprop. |
| **RF-002** | 🟡 partial | **sim** | `NumericValidator` real mas nunca chamado no fluxo vivo; sem par ator/crítico; `ARTIFACT_REJECTED→DAG_GENERATION` é transição morta. |
| **RF-003** | 🟡 partial | parcial | `sqlalchemy.JSON` (não `JSONB`); sem índice GIN; sem Alembic; save único no fim, não por checkpoint. |
| **RF-004** | 🔴 stub | parcial | sem cliente JSON-RPC; sem adapters UniProt/PDB/STRING; registry vazio em produção; não fiado em rota. |
| **RF-005** | 🔴 stub | parcial | sem `runsc`; CI roda `python` puro sem isolamento; só Python (sem bash/R); mock `"42"` local. |
| **RF-006** | 🟡 partial | **sim** | sem `squeue`/`sacct`/`scancel`; sem SFTP/file-sync; sem poll de status. |
| **RF-007** | 🟡 partial | **sim** | libs reais mas presas a demo fixo; sem prop de dados derivados de job. |
| **RF-008** | ⚫ missing | **sim** | zero código: sem entidade manuscrito, sem rota LaTeX, sem editor. |
| **RF-009** | ⚫ missing | **sim** | sem parser YAML frontmatter, sem compiler skill→JSON-Schema, sem loader→registry. |
| **RNF-002** | 🟡 partial | **sim** | denylist substring; bypass `C:\...` drive-letter; sem `os.path.basename`+containment. |
| **RNF-003** | 🟡 partial | parcial | Vault desconectado do Slurm (chave estática); sem TTL modelado. |
| **RNF-004** | ⚫ missing | **sim** | zero spans no caminho de execução sandbox. |
| **RNF-005** | 🔴 stub | **sim** | sanitizer só existe dentro do arquivo de teste; `submit_task` grava task cru no `provenance_log`. |
| **RNF-006** | 🔴 stub | **sim** | ninguém lê/hashea `uv.lock`; `sha256_hash` é string livre sem produtor. |
| **RNF-007** | 🟡 partial | parcial | `get_storage_manager()` hardcoda `use_btrfs=False`; CoW nunca ativa. |
| **RNF-008** | ⚫ missing | parcial | sem check VRAM, sem decisão local/remoto, sem Modal. |
| **RAG-MARKER** | 🔴 stub | parcial | sem ingestão PDF; qdrant-client nunca importado; Neo4j dead code; sem retrieval. |

---

## 4. Backlog priorizado (ordem de execução TDD)

Ordem por **dependência + valor + YAGNI**. Cada item entra pelo teste vermelho.

1. **RF-001** — Entidade `DAG` + orquestrador MCTS (keystone; destrava RF-002/003/004). `domain/entities/dag.py` + `domain/services/mcts_orchestrator.py`.
2. **RNF-005** — `PIISanitizer` fiado no `provenance_log` (violação ativa, fix rápido). `domain/services/pii_sanitizer.py`.
3. **RF-002** — Loop Ator-Crítico no `REVIEW_PENDING` com retry limitado. *(dep RF-001)*
4. **RNF-002** — `path_guard` basename+containment (fecha bypass Windows). `domain/services/path_guard.py`.
5. **RNF-006** — SHA-256 real do `uv.lock` → `ScientificArtifact`. `domain/services/reproducibility.py`.
6. **RF-009** — Parser/compiler `SKILL.md`→JSON-Schema→registry. `infrastructure/skills/`.
7. **RAG-MARKER** — `RetrieveContextUseCase` (Neo4j + novo Qdrant adapter, mockáveis).
8. **RF-004** — Cliente JSON-RPC + adapters bio (respx nos testes). *(dep RF-009, RF-001)*
9. **RF-006** — `squeue`/`sacct` poll + SFTP sync. *(dep RF-001)*
10. **RNF-003** — Fiar OTP Vault no `connect()` do Slurm. *(dep RF-006)*
11. **RF-003** — JSONB+GIN + Alembic + save por checkpoint. *(dep RF-001)*
12. **RF-005** — `execute_bash`/`execute_r_script` + containment compartilhado. *(dep RNF-002)*
13. **RNF-004** — Spans OTel envolvendo execução sandbox (InMemorySpanExporter). *(dep RF-005)*
14. **RNF-008** — Serviço de decisão VRAM + `ModalDispatcher` mock. *(dep RF-006)*
15. **RF-008** — Compilador Tectonic + entidade manuscrito + editor. *(dep RF-002)*
16. **RF-007** — Fiar viewers a `pdbId`/`locus` derivados de job.
17. **RNF-007** — Config `USE_BTRFS` do env em vez de hardcode.

---

## 5. Bloqueado por infra (documentar, não codar aqui)

Precisam de infra que este ambiente Windows não provê — implementamos a **lógica pura testável** e deixamos o adapter atrás de mock/flag:
- **RF-005/RNF-001**: `runsc` não roda em Windows (isolamento real de syscall).
- **RF-003**: JSONB/GIN binário real → precisa Postgres (viável via Docker).
- **RNF-003**: TTL/lease Vault ponta-a-ponta → servidor Vault + vault-ssh-helper.
- **RNF-007**: CoW O(1) real → volume Btrfs/ZFS/ReFS Linux.
- **RF-006**: sbatch/squeue/SFTP contra cluster Slurm vivo.
- **RF-004**: servidores BioContextAI/MCPmed reais + JWT.
- **RNF-008**: GPU real + conta Modal.
- **RAG-MARKER**: modelo Marker (torch/surya-ocr) + Neo4j/Qdrant vivos.

---

## 6. Protocolo de execução (aplicado a cada item)

TDD estrito **Red → Green → Refactor**; Clean Architecture (dependências apontam p/ dentro: domain não importa infra); KISS + YAGNI (só o que o requisito exige, sem abstração especulativa). Gate: suite verde após cada item; rodar arquivo-alvo durante o ciclo, suite completa antes de commit. Um commit por funcionalidade.

---

## 7. Execução concluída (status)

Todo o backlog testável localmente foi implementado via TDD, **um commit atômico por funcionalidade**. Suites finais: **backend 200 passed**, **frontend 38 passed**.

| Item | Commit | Entrega (resumo) |
| :--- | :--- | :--- |
| **RF-001** | `feat(orchestration)` | `DAG`/`MCTSOrchestrator` + `LLMTaskPlanner`; `submit_task` fiado. |
| **RNF-005** | `feat(privacy)` | `PIISanitizer` no `provenance_log`. |
| **RF-002** | `feat(review)` | `NumericReviewer` ator-crítico + loop retry limitado. |
| **RNF-002** | `fix(security)` | `path_guard` basename+containment; fecha bypass `C:\`. |
| **RNF-006** | `feat(provenance)` | SHA-256 do `uv.lock` → `ScientificArtifact`. |
| **RF-009** | `feat(skills)` | `SKILL.md`→JSON-Schema→MCP + gate lockfile. |
| **RNF-007** | `feat(storage)` | flag `USE_BTRFS` do config. |
| **RF-005** | `feat(sandbox)` | `execute_bash`/`execute_r_script`. |
| **RNF-004** | `feat(observability)` | spans OTel `sandbox.execute`. |
| **RF-006** | `feat(hpc)` | `poll_status` (squeue) + SFTP + `JobStatus`. |
| **RNF-003** | `feat(security)` | OTP Vault efêmero no SSH do Slurm. |
| **RNF-008** | `feat(scaling)` | decisão VRAM → Slurm/Modal. |
| **RF-003** | `feat(persistence)` | colunas JSONB (variant) + checkpoint saves. |
| **RAG-MARKER** | `feat(rag)` | `RetrieveContextUseCase` (Neo4j + Qdrant). |
| **RF-004** | `feat(mcp)` | cliente JSON-RPC 2.0 + adapters UniProt/PDB/STRING. |
| **RF-008** | `feat(manuscript)` | entidade manuscrito (crítico) + compilador Tectonic. **Falta:** editor frontend (Monaco/CodeMirror) + rota de compilação. |
| **RF-007** | `feat(frontend)` | viewers Molstar/IGV recebem `pdbId`/`genome`/`locus` de resultado de job. |

**Único item aberto:** editor de manuscrito frontend (RF-008 UI) — construção de UI nova e grande; ao fazê-lo, aplicar as taste-skills de design.

Itens da §5 (infra-bloqueados) permanecem documentados, com a **lógica pura implementada e testada** e o adapter atrás de mock/flag (gVisor runsc, Postgres JSONB/GIN vivo, Vault TTL, cluster Slurm, GPU/Modal, Marker ML).
