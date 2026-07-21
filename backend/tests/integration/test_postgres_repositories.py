import pytest
from uuid import uuid4
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from src.domain.entities.user import User
from src.domain.entities.workspace import Workspace
from src.domain.entities.agent_session import AgentSession
from src.infrastructure.persistence.models import Base, UserModel
from src.infrastructure.persistence.postgres_session_repo import PostgresSessionRepository
from src.infrastructure.persistence.postgres_user_repo import PostgresUserRepository
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


@pytest.mark.asyncio
async def test_postgres_session_repository_persists_dag_generation_attempts(db_session):
    """Regression test for the RF-002 bounded-retry counter reset bug: saving a
    session with a non-zero `dag_generation_attempts` and re-fetching it through a
    brand-new `PostgresSessionRepository` instance (against the same underlying DB)
    must return the same count, not silently reset it to 0.

    A fresh repo instance is used deliberately -- the bug was previously masked by
    the in-memory repository returning the *same object by reference*, which trivially
    "remembers" the attribute regardless of whether the SQL mapping is correct.
    """
    workspace_id = uuid4()

    writer_repo = PostgresSessionRepository(db_session)
    session = AgentSession(workspace_id=workspace_id, dag_generation_attempts=2)
    await writer_repo.save(session)

    # Fresh repo instance -- not the same Python object, and not reusing any cached
    # domain entity -- to prove the count round-trips through the actual DB row.
    reader_repo = PostgresSessionRepository(db_session)
    refetched = await reader_repo.get_by_id(session.id)

    assert refetched is not None
    assert refetched.dag_generation_attempts == 2


@pytest.mark.asyncio
async def test_postgres_user_repository_get_by_id_missing_returns_none(db_session):
    user_repo = PostgresUserRepository(db_session)
    assert await user_repo.get_by_id(uuid4()) is None


@pytest.mark.asyncio
async def test_postgres_user_repository_save_inserts_then_updates(db_session):
    user_repo = PostgresUserRepository(db_session)

    user = User(email="researcher@osw.org")
    await user_repo.save(user)

    persisted = await user_repo.get_by_id(user.id)
    assert persisted is not None
    assert persisted.email == "researcher@osw.org"
    assert persisted.iam_role == "scientist"

    # Saving again with the same id updates the existing row instead of inserting
    # a second one (exercises the "model already exists" branch of save()).
    persisted.iam_role = "admin"
    await user_repo.save(persisted)

    updated = await user_repo.get_by_id(user.id)
    assert updated.iam_role == "admin"


@pytest.mark.asyncio
async def test_postgres_workspace_repository_save_updates_existing_workspace(db_session):
    workspace_repo = PostgresWorkspaceRepository(db_session)

    user_id = uuid4()
    workspace = Workspace(owner_id=user_id, fs_mount_path="test_workspace_2")
    await workspace_repo.save(workspace)

    # Saving again with the same id updates the existing row (exercises the
    # "model already exists" branch of save()) instead of inserting a duplicate.
    workspace.is_fork = True
    await workspace_repo.save(workspace)

    updated = await workspace_repo.get_by_id(workspace.id)
    assert updated is not None
    assert updated.is_fork is True
