"""RF-003: dag_snapshot/provenance_log must map to JSONB on PostgreSQL (with a
JSON fallback on SQLite so the test DB still builds)."""
from sqlalchemy.dialects.postgresql import JSONB

from src.infrastructure.persistence.models import AgentSessionModel


def test_jsonb_columns_use_postgres_jsonb_variant():
    for column_name in ("dag_snapshot", "provenance_log"):
        col_type = AgentSessionModel.__table__.c[column_name].type
        variant = col_type._variant_mapping.get("postgresql")
        assert isinstance(variant, JSONB), f"{column_name} is not JSONB on postgresql"
