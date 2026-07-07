"""
Real-path tests for `Neo4jGraphClient` (Fase 4). The `neo4j.AsyncGraphDatabase`
driver is mocked at the transport boundary (`AsyncGraphDatabase.driver(...)` /
`AsyncDriver.execute_query(...)`) so these tests exercise the *real* Cypher
query construction and result parsing without requiring a live Neo4j server,
which does not exist in this sandbox.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from neo4j import RoutingControl

from src.infrastructure.graph import neo4j_client as neo4j_client_module
from src.infrastructure.graph.neo4j_client import Neo4jGraphClient


def _make_fake_driver(execute_query_return=None):
    driver = MagicMock(name="async_driver")
    driver.execute_query = AsyncMock(return_value=execute_query_return)
    driver.close = AsyncMock()
    return driver


@pytest.mark.asyncio
async def test_neo4j_client_real_add_triple_runs_merge_query(monkeypatch):
    driver = _make_fake_driver(execute_query_return=([], None, None))
    fake_database = MagicMock()
    fake_database.driver.return_value = driver
    monkeypatch.setattr(neo4j_client_module, "AsyncGraphDatabase", fake_database)

    client = Neo4jGraphClient(uri="bolt://real-neo4j:7687", user="neo4j", password="s3cret")
    assert client._is_mock is False

    await client.add_triple("TP53", "interacts_with", "MDM2")

    fake_database.driver.assert_called_once_with("bolt://real-neo4j:7687", auth=("neo4j", "s3cret"))
    driver.execute_query.assert_awaited_once()
    query_arg, kwargs = driver.execute_query.call_args
    assert "MERGE" in query_arg[0]
    assert "RELATES_TO" in query_arg[0]
    assert kwargs == {"subject": "TP53", "predicate": "interacts_with", "object_entity": "MDM2"}


@pytest.mark.asyncio
async def test_neo4j_client_real_get_relations_parses_records(monkeypatch):
    fake_records = [
        {"predicate": "interacts_with", "object": "MDM2"},
        {"predicate": "regulates", "object": "CDKN1A"},
    ]
    driver = _make_fake_driver(execute_query_return=(fake_records, None, None))
    fake_database = MagicMock()
    fake_database.driver.return_value = driver
    monkeypatch.setattr(neo4j_client_module, "AsyncGraphDatabase", fake_database)

    client = Neo4jGraphClient(uri="bolt://real-neo4j:7687", user="neo4j", password="s3cret")

    relations = await client.get_relations("TP53")

    driver.execute_query.assert_awaited_once()
    query_arg, kwargs = driver.execute_query.call_args
    assert "MATCH" in query_arg[0]
    assert kwargs["subject"] == "TP53"
    assert kwargs["routing_"] == RoutingControl.READ

    assert relations == [
        {"subject": "TP53", "predicate": "interacts_with", "object": "MDM2"},
        {"subject": "TP53", "predicate": "regulates", "object": "CDKN1A"},
    ]


@pytest.mark.asyncio
async def test_neo4j_client_real_driver_created_once_and_reused(monkeypatch):
    driver = _make_fake_driver(execute_query_return=([], None, None))
    fake_database = MagicMock()
    fake_database.driver.return_value = driver
    monkeypatch.setattr(neo4j_client_module, "AsyncGraphDatabase", fake_database)

    client = Neo4jGraphClient(uri="bolt://real-neo4j:7687", user="neo4j", password="s3cret")
    await client.add_triple("A", "rel", "B")
    await client.add_triple("C", "rel", "D")

    # `driver(...)` is only constructed once and reused across calls.
    fake_database.driver.assert_called_once()


@pytest.mark.asyncio
async def test_neo4j_client_close_closes_real_driver(monkeypatch):
    driver = _make_fake_driver(execute_query_return=([], None, None))
    fake_database = MagicMock()
    fake_database.driver.return_value = driver
    monkeypatch.setattr(neo4j_client_module, "AsyncGraphDatabase", fake_database)

    client = Neo4jGraphClient(uri="bolt://real-neo4j:7687", user="neo4j", password="s3cret")
    await client.add_triple("A", "rel", "B")
    await client.close()

    driver.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_neo4j_client_close_is_noop_when_never_connected():
    # Mock-mode client that never touched the real driver must not blow up on close().
    client = Neo4jGraphClient(uri="bolt://mock-neo4j:7687", password="")
    await client.close()
