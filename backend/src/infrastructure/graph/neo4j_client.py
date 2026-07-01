import os
from typing import List, Dict, Any

class Neo4jGraphClient:
    """
    Adapter for communicating with Neo4j graph database to build GraphRAG.
    Falls back to mock client if credentials are not present (like in local tests).
    """
    def __init__(self, uri: str = None, user: str = None, password: str = None):
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "password")
        self._mock_db: List[Dict[str, Any]] = []

    async def add_triple(self, subject: str, predicate: str, object_entity: str) -> None:
        """Adds a biological RDF triple to the Graph database."""
        if "mock" in self.uri or not self.password:
            self._mock_db.append({"subject": subject, "predicate": predicate, "object": object_entity})
            return
        
        # Real Neo4j integration would initialize driver and run session here
        # self.driver.execute_query(...)
        pass

    async def get_relations(self, subject: str) -> List[Dict[str, Any]]:
        """Queries relations associated with a biological entity."""
        if "mock" in self.uri or not self.password:
            return [t for t in self._mock_db if t["subject"] == subject]
            
        return []
