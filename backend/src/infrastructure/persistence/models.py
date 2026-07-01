from sqlalchemy import Column, String, Boolean, ForeignKey, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import declarative_base, relationship
import uuid
import datetime

Base = declarative_base()

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
    dag_snapshot = Column(JSON, nullable=False, default=dict)
    provenance_log = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
