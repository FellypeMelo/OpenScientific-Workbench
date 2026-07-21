from sqlalchemy import Column, String, Boolean, ForeignKey, DateTime, Integer, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import declarative_base, relationship
import uuid
import datetime

Base = declarative_base()

# JSONB on PostgreSQL (binary storage + containment/GIN queries for MCTS trees,
# RF-003) with a plain-JSON fallback on SQLite so the dev/CI test DB still builds.
# A GIN index on these columns is a Postgres-only optimisation and belongs in an
# Alembic migration (the live-Postgres track), not in create_all against SQLite.
_JSONB = JSON().with_variant(JSONB(), "postgresql")

class UserModel(Base):
    __tablename__ = "users"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False)
    iam_role = Column(String(50), nullable=False, default="scientist")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class WorkspaceModel(Base):
    __tablename__ = "workspaces"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    fs_mount_path = Column(String(255), unique=True, nullable=False)
    is_fork = Column(Boolean, default=False)
    parent_workspace_id = Column(PG_UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class AgentSessionModel(Base):
    __tablename__ = "agent_sessions"
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(PG_UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"))
    session_status = Column(String(50), default="INITIALIZING")
    dag_snapshot = Column(_JSONB, nullable=False, default=dict)
    provenance_log = Column(_JSONB, nullable=False, default=list)
    # Number of DAG (re)generation attempts, mirroring
    # `AgentSession.dag_generation_attempts` (domain/entities/agent_session.py).
    # Must round-trip through get_by_id()/save() below -- without persisting this
    # column, every fresh fetch of a session resets the actor-critic retry counter
    # to 0, silently breaking the RF-002 bounded-retry guarantee across requests.
    dag_generation_attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class ArtifactModel(Base):
    __tablename__ = "artifacts"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(PG_UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="CASCADE"))
    name = Column(String(255), nullable=False)
    # 64 lowercase hex chars (SHA-256), mirrors
    # `ScientificArtifact.validate_sha256` (domain/entities/scientific_artifact.py).
    sha256_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
