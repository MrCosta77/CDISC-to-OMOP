import duckdb
import pandas as pd

from src.mapping.deterministic_mapping import process_domain
from src.utils.run_context import ensure_audit_schema


def test_deterministic_mapping_records_run_id_without_duplicates():
    source = pd.DataFrame(
        {
            "condition_occurrence_id": [101],
            "condition_source_value": ["Hypertension"],
            "condition_concept_id": [0],
        }
    )

    with duckdb.connect(":memory:") as con:
        con.execute("""
            CREATE TABLE concept (
                concept_id INTEGER,
                concept_name VARCHAR,
                domain_id VARCHAR,
                standard_concept VARCHAR
            )
        """)
        con.execute("""
            INSERT INTO concept VALUES (320128, 'Hypertension', 'Condition', 'S')
        """)
        con.execute("""
            CREATE TABLE concept_relationship (
                concept_id_1 INTEGER,
                concept_id_2 INTEGER,
                relationship_id VARCHAR
            )
        """)
        ensure_audit_schema(con)

        for _ in range(2):
            mapped, count = process_domain(
                source.copy(),
                "condition_source_value",
                "condition_concept_id",
                "condition_occurrence_id",
                "Condition",
                "condition_occurrence",
                con,
                "RUN-TEST",
            )
            assert count == 1
            assert mapped.loc[0, "condition_concept_id"] == 320128

        audit = con.execute("""
            SELECT run_id, assigned_concept_id, COUNT(*)
            FROM mapping_provenance
            GROUP BY run_id, assigned_concept_id
        """).fetchone()

    assert audit == ("RUN-TEST", 320128, 1)
