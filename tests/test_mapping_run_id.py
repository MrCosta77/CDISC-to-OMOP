import duckdb
import pandas as pd

from src.mapping.deterministic_mapping import get_standard_concept, process_domain
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
                standard_concept VARCHAR,
                invalid_reason VARCHAR,
                valid_start_date DATE,
                valid_end_date DATE
            )
        """)
        con.execute("""
            INSERT INTO concept VALUES (
                320128, 'Hypertension', 'Condition', 'S', NULL,
                '1970-01-01', '2099-12-31'
            )
        """)
        con.execute("""
            CREATE TABLE concept_relationship (
                concept_id_1 INTEGER,
                concept_id_2 INTEGER,
                relationship_id VARCHAR,
                invalid_reason VARCHAR,
                valid_start_date DATE,
                valid_end_date DATE
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


def test_deterministic_mapping_ignores_expired_concepts_and_breaks_ties():
    with duckdb.connect(":memory:") as con:
        con.execute("""
            CREATE TABLE concept (
                concept_id INTEGER, concept_name VARCHAR, domain_id VARCHAR,
                standard_concept VARCHAR, invalid_reason VARCHAR,
                valid_start_date DATE, valid_end_date DATE
            )
        """)
        con.executemany("""
            INSERT INTO concept VALUES (?, 'Same term', 'Condition', 'S', NULL,
                                        '1970-01-01', ?)
        """, [(1, "2000-12-31"), (20, "2099-12-31"), (10, "2099-12-31")])
        con.execute("""
            CREATE TABLE concept_relationship (
                concept_id_1 INTEGER, concept_id_2 INTEGER,
                relationship_id VARCHAR, invalid_reason VARCHAR,
                valid_start_date DATE, valid_end_date DATE
            )
        """)

        result = get_standard_concept("Same term", "Condition", con)

    assert result == (10, "Same term", "deterministic_direct_match")
