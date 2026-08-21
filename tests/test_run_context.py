import json

import duckdb

from src.utils.run_context import (
    ensure_audit_schema,
    finish_pipeline_run,
    generate_run_id,
    start_pipeline_run,
)


def test_pipeline_run_lifecycle(tmp_path):
    db_path = tmp_path / "audit.duckdb"
    run_id = generate_run_id()

    start_pipeline_run(
        run_id,
        db_path=db_path,
        input_manifest={"raw": {"dm.sas7bdat": {"sha256": "abc"}}},
        snapshot={"model_name": "test-model"},
        git_commit="deadbeef",
    )
    finish_pipeline_run(
        run_id,
        "SUCCESS",
        output_counts={"person": 10},
        db_path=db_path,
    )

    with duckdb.connect(str(db_path), read_only=True) as con:
        row = con.execute(
            """
            SELECT status, finished_at, git_commit, input_manifest_json,
                   config_snapshot_json, output_counts_json, error_message
            FROM pipeline_run
            WHERE run_id = ?
            """,
            [run_id],
        ).fetchone()

    assert row[0] == "SUCCESS"
    assert row[1] is not None
    assert row[2] == "deadbeef"
    assert json.loads(row[3])["raw"]["dm.sas7bdat"]["sha256"] == "abc"
    assert json.loads(row[4])["model_name"] == "test-model"
    assert json.loads(row[5]) == {"person": 10}
    assert row[6] is None


def test_legacy_provenance_is_migrated_and_new_rows_are_idempotent(tmp_path):
    db_path = tmp_path / "legacy.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute("CREATE SEQUENCE seq_provenance_id START 3")
        con.execute("""
            CREATE TABLE mapping_provenance (
                provenance_id BIGINT PRIMARY KEY
                    DEFAULT nextval('seq_provenance_id'),
                target_table VARCHAR NOT NULL,
                target_id BIGINT NOT NULL,
                source_value VARCHAR,
                normalized_value VARCHAR,
                assigned_concept_id INTEGER NOT NULL,
                mapping_method VARCHAR NOT NULL,
                score DOUBLE NOT NULL,
                model_name VARCHAR,
                vocabulary_version VARCHAR,
                reviewed_by VARCHAR,
                created_at TIMESTAMP
            )
        """)
        con.execute("""
            INSERT INTO mapping_provenance VALUES (
                1, 'condition_occurrence', 1, 'legacy', 'legacy', 0,
                'legacy_method', 0, NULL, NULL, NULL, CURRENT_TIMESTAMP
            )
        """)
        con.execute("""
            INSERT INTO mapping_provenance VALUES (
                2, 'condition_occurrence', 1, 'legacy', 'legacy', 0,
                'legacy_method', 0, NULL, NULL, NULL, CURRENT_TIMESTAMP
            )
        """)

        ensure_audit_schema(con)

        columns = {
            row[1]
            for row in con.execute(
                "PRAGMA table_info('mapping_provenance')"
            ).fetchall()
        }
        assert "run_id" in columns
        assert con.execute(
            "SELECT COUNT(*) FROM mapping_provenance WHERE run_id IS NULL"
        ).fetchone()[0] == 2

        statement = """
            INSERT INTO mapping_provenance (
                target_table, target_id, source_value, normalized_value,
                assigned_concept_id, mapping_method, score, run_id
            ) VALUES ('condition_occurrence', 2, 'new', 'new', 123,
                      'deterministic_direct_match', 1.0, 'RUN-TEST')
            ON CONFLICT DO NOTHING
        """
        con.execute(statement)
        con.execute(statement)

        assert con.execute(
            "SELECT COUNT(*) FROM mapping_provenance WHERE run_id = 'RUN-TEST'"
        ).fetchone()[0] == 1
