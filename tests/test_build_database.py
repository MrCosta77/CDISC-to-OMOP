import duckdb
import pandas as pd
import pytest

from src.etl.build_database import build_omop_database


PROCESSED_FILES = (
    "PERSON.csv",
    "VISIT_OCCURRENCE.csv",
    "CONDITION_OCCURRENCE.csv",
    "DRUG_EXPOSURE.csv",
    "MEASUREMENT.csv",
    "OBSERVATION_PERIOD.csv",
)


def test_database_build_publishes_all_tables(tmp_path):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    for index, filename in enumerate(PROCESSED_FILES, start=1):
        pd.DataFrame({"record_id": [index]}).to_csv(
            processed_dir / filename, index=False
        )

    db_path = tmp_path / "omop.duckdb"
    build_omop_database(db_path=db_path, processed_dir=processed_dir)

    expected_tables = {
        filename.removesuffix(".csv").lower() for filename in PROCESSED_FILES
    }
    with duckdb.connect(str(db_path), read_only=True) as con:
        actual_tables = {
            row[0]
            for row in con.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main'
                """
            ).fetchall()
        }
        assert expected_tables <= actual_tables
        for table in expected_tables:
            assert con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 1


def test_missing_output_aborts_before_existing_database_is_changed(tmp_path):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    pd.DataFrame({"person_id": [99]}).to_csv(
        processed_dir / "PERSON.csv", index=False
    )

    db_path = tmp_path / "omop.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute("CREATE TABLE person (person_id INTEGER)")
        con.execute("INSERT INTO person VALUES (7)")

    with pytest.raises(FileNotFoundError, match="Missing processed files"):
        build_omop_database(db_path=db_path, processed_dir=processed_dir)

    with duckdb.connect(str(db_path), read_only=True) as con:
        assert con.execute("SELECT person_id FROM person").fetchall() == [(7,)]
