import pytest
from uuid import uuid4
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from src.domain.entities.user import User
from src.domain.entities.workspace import Workspace
from src.domain.entities.agent_session import AgentSession
from src.infrastructure.persistence.models import Base, UserModel
from src.infrastructure.persistence.postgres_session_repo import PostgresSessionRepository
from src.infrastructure.persistence.postgres_workspace_repo import PostgresWorkspaceRepository

@pytest.fixture
async def db_session():
    # Set up in-memory SQLite database for local integration testing
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session() as session:
        yield session

@pytest.mark.asyncio
async def test_postgres_repositories_integration(db_session):
    session_repo = PostgresSessionRepository(db_session)
    workspace_repo = PostgresWorkspaceRepository(db_session)
    
    # 1. Prepopulate a user model in DB
    user_id = uuid4()
    user_model = UserModel(id=user_id, email="scientist@osw.org")
    db_session.add(user_model)
    await db_session.commit()
    
    # 2. Test Workspace persistence
    workspace = Workspace(owner_id=user_id, fs_mount_path="test_workspace_1")
    await workspace_repo.save(workspace)
    
    retrieved_workspace = await workspace_repo.get_by_id(workspace.id)
    assert retrieved_workspace is not None
    assert retrieved_workspace.id == workspace.id
    assert retrieved_workspace.fs_mount_path == "test_workspace_1"
    
    # 3. Test AgentSession persistence
    session = AgentSession(workspace_id=workspace.id)
    await session_repo.save(session)
    
    retrieved_session = await session_repo.get_by_id(session.id)
    assert retrieved_session is not None
    assert retrieved_session.id == session.id
    assert retrieved_session.session_status == "INITIALIZING"
    assert retrieved_session.dag_snapshot == {}
    
    # 4. Test updating AgentSession
    retrieved_session.transition_to("DAG_GENERATION")
    retrieved_session.dag_snapshot = {"completed": False}
    await session_repo.save(retrieved_session)
    
    updated_session = await session_repo.get_by_id(session.id)
    assert updated_session.session_status == "DAG_GENERATION"
    assert updated_session.dag_snapshot == {"completed": False}
