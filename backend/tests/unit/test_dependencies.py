"""
Unit tests for `get_current_user_id` (`src/presentation/dependencies.py`),
the IDOR-fix dependency every route now uses to resolve "who is asking" from
the authenticated JWT claims instead of any client-supplied identifier.

Uses a minimal duck-typed stand-in for `fastapi.Request` (only `.state` is
read by the function under test) rather than constructing a real Starlette
`Request` -- this is a focused unit test of the dependency's own logic, not
an HTTP-transport test (that coverage lives in `test_idor_ownership.py` and
`test_presentation_routes.py`, exercised through real routes).
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.presentation.dependencies import get_current_user_id


def _fake_request(user=None) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(user=user) if user is not None else SimpleNamespace())


def test_returns_the_sub_claim_as_a_string():
    request = _fake_request(user={"sub": "11111111-1111-1111-1111-111111111111", "iam_role": "scientist"})
    assert get_current_user_id(request) == "11111111-1111-1111-1111-111111111111"


def test_raises_401_when_state_has_no_user_attribute_at_all():
    request = _fake_request(user=None)
    with pytest.raises(HTTPException) as exc_info:
        get_current_user_id(request)
    assert exc_info.value.status_code == 401


def test_raises_401_when_user_claims_are_missing_sub():
    request = _fake_request(user={"iam_role": "scientist"})
    with pytest.raises(HTTPException) as exc_info:
        get_current_user_id(request)
    assert exc_info.value.status_code == 401


def test_raises_401_when_user_is_not_a_dict():
    request = SimpleNamespace(state=SimpleNamespace(user="not-a-dict"))
    with pytest.raises(HTTPException) as exc_info:
        get_current_user_id(request)
    assert exc_info.value.status_code == 401


def test_get_sandbox_driver_wires_a_real_tracer(monkeypatch):
    """RNF-004 gap closure: the sandbox driver's real construction site
    (`get_sandbox_driver`) must pass `tracer=get_tracer()` so `sandbox.execute`
    spans actually emit once telemetry is booted -- `BubblewrapSandboxDriver`
    itself defaults `tracer=None` (no spans at all) unless a caller wires one
    in (see `infrastructure/sandbox/bubblewrap_driver.py`).

    `SANDBOX_RUNTIME=mock` avoids needing a real `bwrap` binary on this
    (Windows dev sandbox) test host, same pattern `test_task_routes.py` uses.
    """
    import src.presentation.dependencies as dependencies

    monkeypatch.setattr(dependencies.settings, "SANDBOX_RUNTIME", "mock")

    driver = dependencies.get_sandbox_driver()

    assert driver.tracer is not None
    # Duck-typed check (avoids pinning to OTel's internal proxy-tracer class):
    # a real tracer exposes `start_as_current_span`, which is exactly what
    # `BubblewrapSandboxDriver`'s span-wrapping code calls on it.
    assert hasattr(driver.tracer, "start_as_current_span")


def test_get_artifact_repository_returns_a_postgres_artifact_repository():
    """New DI provider (RNF-006 gap closure): mirrors `get_session_repository`
    / `get_workspace_repository`'s "wraps the request-scoped `AsyncSession` in
    the real Postgres-pattern adapter" shape."""
    from unittest.mock import MagicMock

    from src.presentation.dependencies import get_artifact_repository
    from src.infrastructure.persistence.postgres_artifact_repo import PostgresArtifactRepository

    fake_session = MagicMock()
    repo = get_artifact_repository(session=fake_session)

    assert isinstance(repo, PostgresArtifactRepository)
    assert repo.db_session is fake_session


class TestRagStoreSingletons:
    """RAG-MARKER gap closure: `get_vector_store`/`get_graph_store` are
    process-wide singletons (unlike every other `Depends()` factory in this
    module, which constructs a fresh instance per call) so their real,
    lazily-created connection pool is built once and released exactly once
    via `close_vector_store`/`close_graph_store` -- see the module docstring
    comment directly above them."""

    @pytest.fixture(autouse=True)
    def _reset_singletons(self):
        import src.presentation.dependencies as dependencies

        dependencies._vector_store = None
        dependencies._graph_store = None
        yield
        dependencies._vector_store = None
        dependencies._graph_store = None

    def test_get_vector_store_returns_a_qdrant_vector_store(self):
        from src.infrastructure.vector.qdrant_client import QdrantVectorStore
        from src.presentation.dependencies import get_vector_store

        store = get_vector_store()

        assert isinstance(store, QdrantVectorStore)

    def test_get_vector_store_returns_the_same_instance_across_calls(self):
        from src.presentation.dependencies import get_vector_store

        first = get_vector_store()
        second = get_vector_store()

        assert first is second

    @pytest.mark.asyncio
    async def test_close_vector_store_closes_and_clears_the_singleton(self):
        import src.presentation.dependencies as dependencies
        from src.presentation.dependencies import close_vector_store, get_vector_store

        store = get_vector_store()
        closed = {"called": False}

        async def _fake_close():
            closed["called"] = True

        store.close = _fake_close

        await close_vector_store()

        assert closed["called"] is True
        assert dependencies._vector_store is None

    @pytest.mark.asyncio
    async def test_close_vector_store_is_noop_when_never_constructed(self):
        from src.presentation.dependencies import close_vector_store

        await close_vector_store()  # must not raise

    def test_get_graph_store_returns_a_neo4j_graph_client(self):
        from src.infrastructure.graph.neo4j_client import Neo4jGraphClient
        from src.presentation.dependencies import get_graph_store

        store = get_graph_store()

        assert isinstance(store, Neo4jGraphClient)

    def test_get_graph_store_returns_the_same_instance_across_calls(self):
        from src.presentation.dependencies import get_graph_store

        first = get_graph_store()
        second = get_graph_store()

        assert first is second

    @pytest.mark.asyncio
    async def test_close_graph_store_closes_and_clears_the_singleton(self):
        import src.presentation.dependencies as dependencies
        from src.presentation.dependencies import close_graph_store, get_graph_store

        store = get_graph_store()
        closed = {"called": False}

        async def _fake_close():
            closed["called"] = True

        store.close = _fake_close

        await close_graph_store()

        assert closed["called"] is True
        assert dependencies._graph_store is None

    @pytest.mark.asyncio
    async def test_close_graph_store_is_noop_when_never_constructed(self):
        from src.presentation.dependencies import close_graph_store

        await close_graph_store()  # must not raise


def test_get_document_parser_returns_a_pypdf_document_parser():
    from src.infrastructure.parsing.pypdf_adapter import PypdfDocumentParser
    from src.presentation.dependencies import get_document_parser

    parser = get_document_parser()

    assert isinstance(parser, PypdfDocumentParser)
