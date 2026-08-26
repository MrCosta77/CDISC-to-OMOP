import json

import duckdb
import pytest

from src.utils.run_context import (
    build_source_manifest,
    carry_forward_pipeline_history,
    ensure_audit_schema,
    finish_pipeline_run,
    generate_run_id,
    require_publishable_source_state,
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
        source_state={
            "git_commit": "ignored-by-explicit-argument",
            "git_is_dirty": False,
            "source_tree_sha256": "source123",
            "source_manifest": {"files": {"main.py": "abc"}},
        },
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
            SELECT status, finished_at, git_commit, git_is_dirty,
                   source_tree_sha256, source_manifest_json, input_manifest_json,
                   config_snapshot_json, output_counts_json, error_message
            FROM pipeline_run
            WHERE run_id = ?
            """,
            [run_id],
        ).fetchone()

    assert row[0] == "SUCCESS"
    assert row[1] is not None
    assert row[2] == "deadbeef"
    assert row[3] is False
    assert row[4] == "source123"
    assert json.loads(row[5])["files"]["main.py"] == "abc"
    assert json.loads(row[6])["raw"]["dm.sas7bdat"]["sha256"] == "abc"
    assert json.loads(row[7])["model_name"] == "test-model"
    assert json.loads(row[8]) == {"person": 10}
    assert row[9] is None


def test_source_manifest_changes_with_executable_source(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "main.py").write_text("print('one')\n", encoding="utf-8")
    module = tmp_path / "src" / "module.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    first = build_source_manifest(tmp_path)

    module.write_text("VALUE = 2\n", encoding="utf-8")
    second = build_source_manifest(tmp_path)

    assert first["source_tree_sha256"] != second["source_tree_sha256"]
    assert set(second["files"]) == {"main.py", "src/module.py"}


def test_dirty_source_is_rejected_unless_explicitly_allowed():
    state = {
        "git_commit": "abc123",
        "git_is_dirty": True,
        "git_status": [" M src/module.py"],
    }
    with pytest.raises(RuntimeError, match="dirty Git working tree"):
        require_publishable_source_state(state, allow_dirty=False)
    require_publishable_source_state(state, allow_dirty=True)


def test_unknown_git_source_is_rejected_unless_explicitly_allowed():
    state = {"git_commit": None, "git_is_dirty": None, "git_status": []}
    with pytest.raises(RuntimeError, match="could not be determined"):
        require_publishable_source_state(state, allow_dirty=False)
    require_publishable_source_state(state, allow_dirty=True)

    inconsistent_state = {
        "git_commit": None,
        "git_is_dirty": False,
        "git_status": [],
    }
    with pytest.raises(RuntimeError, match="could not be determined"):
        require_publishable_source_state(inconsistent_state, allow_dirty=False)


def test_pipeline_run_history_is_carried_forward_idempotently(tmp_path):
    source = tmp_path / "published.duckdb"
    target = tmp_path / "candidate.duckdb"
    state = {
        "git_commit": "abc123",
        "git_is_dirty": False,
        "source_tree_sha256": "tree123",
        "source_manifest": {"files": {"main.py": "hash"}},
    }
    start_pipeline_run(
        "RUN-OLD",
        db_path=source,
        input_manifest={},
        snapshot={},
        source_state=state,
    )
    finish_pipeline_run("RUN-OLD", "SUCCESS", db_path=source)

    assert carry_forward_pipeline_history(source, target) == 1
    assert carry_forward_pipeline_history(source, target) == 1
    with duckdb.connect(str(target), read_only=True) as con:
        rows = con.execute("""
            SELECT run_id, status, git_commit, git_is_dirty,
                   source_tree_sha256
            FROM pipeline_run
        """).fetchall()
    assert rows == [("RUN-OLD", "SUCCESS", "abc123", False, "tree123")]


def test_legacy_provenance_is_migrated_and_new_rows_are_idempotent(tmp_path):
    db_path = tmp_path / "legacy.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute("""
            CREATE TABLE pipeline_run (
                run_id VARCHAR PRIMARY KEY,
                status VARCHAR NOT NULL,
                started_at TIMESTAMP NOT NULL,
                finished_at TIMESTAMP,
                git_commit VARCHAR,
                input_manifest_json VARCHAR,
                config_snapshot_json VARCHAR,
                output_counts_json VARCHAR,
                error_message VARCHAR
            )
        """)
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

        pipeline_columns = {
            row[1]
            for row in con.execute("PRAGMA table_info('pipeline_run')").fetchall()
        }
        assert {
            "git_is_dirty", "source_tree_sha256", "source_manifest_json"
        } <= pipeline_columns

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
