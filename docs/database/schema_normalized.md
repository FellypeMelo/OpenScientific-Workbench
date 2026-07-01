# Esquema SQL Normalizado e Sessões
**ID Documento:** ARCH-DB-001 | **Status:** Aprovado | **Versão:** 1.0.0

A camada relacional do OSW (PostgreSQL) serve exclusivamente para gerir os Metadados, Histórico de Sessões do Agente e Políticas de IAM, utilizando `JSONB` de forma agressiva para armazenar grafos e logs PydanticAI.

## 1. Esquema de Entidades (PostgreSQL)

```sql
-- Habilita extensão para UUID automático
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    iam_role VARCHAR(50) NOT NULL DEFAULT 'scientist',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE workspaces (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_id UUID REFERENCES users(id) ON DELETE CASCADE,
    fs_mount_path VARCHAR(255) NOT NULL UNIQUE,
    is_fork BOOLEAN DEFAULT FALSE,
    parent_workspace_id UUID REFERENCES workspaces(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE agent_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
    session_status VARCHAR(50) DEFAULT 'INITIALIZING',
    dag_snapshot JSONB NOT NULL DEFAULT '{}',
    provenance_log JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Índices GIN para busca full-text e estrutural em logs e DAGs
CREATE INDEX idx_sessions_dag_jsonb ON agent_sessions USING GIN (dag_snapshot);
CREATE INDEX idx_sessions_prov_jsonb ON agent_sessions USING GIN (provenance_log);
```

## 2. Idempotência e Auditoria
Todo script de migração DDL deve possuir checagens `IF NOT EXISTS` para idempotência estrutural. Tabela `agent_sessions` é de inserção progressiva (Event Sourcing parcial) para permitir "Time-Travel Debugging" da memória do agente.
