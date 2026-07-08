"""
Neo4j GraphRAG adapter (Fase 4 - real `neo4j` async driver integration).

Design notes:
- Falls back to a simple in-memory list (the historical mock) whenever
  `self.uri` contains `"mock"` (existing test/local-dev convention) or
  `self.password` is falsy -- mirroring the same "real infra not configured"
  gating pattern used by the other Fase 4 adapters (Vault/Slurm), so a fresh
  checkout / CI runner / local dev machine without a running Neo4j instance
  still boots and the test suite stays deterministic.
- Real reads/writes use `neo4j.AsyncGraphDatabase.driver(...)` +
  `AsyncDriver.execute_query(...)` (the unified, retry-aware convenience API
  the driver has provided since 5.x), not raw `session.run` -- this is the
  documented preferred entry point for one-off queries.
- Relationship type is intentionally NOT the raw `predicate` string
  interpolated into the Cypher text. Cypher does not support parameterizing
  relationship types (only property values), and `predicate` is arbitrary
  external input (a biological relation name) -- string-formatting it
  directly into the query would be a Cypher injection vector. Instead every
  edge uses a single, fixed relationship type `RELATES_TO` with `predicate`
  stored as a fully-parameterized property, which is both injection-safe and
  faithfully reversible (`get_relations` reads `r.predicate` back out) without
  needing an allow-list of relationship-type strings.
"""
import os
from typing import Any, Dict, List

from neo4j import AsyncGraphDatabase, RoutingControl

from src.infrastructure.config import settings


class Neo4jGraphClient:
    """
    Adapter for communicating with Neo4j graph database to build GraphRAG.
    Falls back to mock client if credentials are not present (like in local tests).
    """

    def __init__(self, uri: str = None, user: str = None, password: str = None):
        self.uri = uri or os.getenv("NEO4J_URI", settings.NEO4J_URI)
        self.user = user or os.getenv("NEO4J_USER", settings.NEO4J_USER)
        # `password` uses an explicit `is not None` check (not `or`) so callers
        # (like the mock unit test) can pass `password=""` to force the mock
        # path without it being masked by an env/settings fallback.
        self.password = (
            password if password is not None else os.getenv("NEO4J_PASSWORD", settings.NEO4J_PASSWORD)
        )
        self._mock_db: List[Dict[str, Any]] = []
        # Lazily-created real driver; only ever instantiated on the real path.
        self._driver = None

    @property
    def _is_mock(self) -> bool:
        return "mock" in self.uri or not self.password

    def _get_driver(self):
        if self._driver is None:
            self._driver = AsyncGraphDatabase.driver(self.uri, auth=(self.user, self.password))
        return self._driver

    async def add_triple(self, subject: str, predicate: str, object_entity: str) -> None:
        """Adds a biological RDF triple to the Graph database."""
        if self._is_mock:
            self._mock_db.append({"subject": subject, "predicate": predicate, "object": object_entity})
            return

        driver = self._get_driver()
        await driver.execute_query(
            "MERGE (s:Entity {name: $subject}) "
            "MERGE (o:Entity {name: $object_entity}) "
            "MERGE (s)-[r:RELATES_TO {predicate: $predicate}]->(o)",
            subject=subject,
            predicate=predicate,
            object_entity=object_entity,
        )

    async def get_relations(self, subject: str) -> List[Dict[str, Any]]:
        """Queries relations associated with a biological entity."""
        if self._is_mock:
            return [t for t in self._mock_db if t["subject"] == subject]

        driver = self._get_driver()
        records, _, _ = await driver.execute_query(
            "MATCH (s:Entity {name: $subject})-[r:RELATES_TO]->(o:Entity) "
            "RETURN r.predicate AS predicate, o.name AS object",
            subject=subject,
            routing_=RoutingControl.READ,
        )
        return [
            {"subject": subject, "predicate": record["predicate"], "object": record["object"]}
            for record in records
        ]

    async def close(self) -> None:
        """Releases the real driver's connection pool, if one was created."""
        if self._driver is not None:
            await self._driver.close()
            self._driver = None
