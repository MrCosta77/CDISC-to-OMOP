import duckdb

from src.omop.cdm54 import validate_table_schema
from src.utils.setup_audit import setup_audit_tables


def test_cdm_source_uses_pinned_omop_contract(tmp_path):
    db_path = tmp_path / "audit.duckdb"

    setup_audit_tables(db_path)

    with duckdb.connect(str(db_path), read_only=True) as con:
        assert validate_table_schema(con, "cdm_source")
        assert con.execute("""
            SELECT cdm_version, cdm_version_concept_id
            FROM cdm_source
        """).fetchone() == ("5.4", 756265)
