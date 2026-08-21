from pathlib import Path

import duckdb
import pytest

from src.omop.cdm54 import (
    CDM_RELEASE,
    create_table_sql,
    expected_columns,
    load_table_specs,
    validate_table_schema,
    verify_specification,
)
from src.utils.setup_cdm_schema import setup_cdm_schema


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC_GIT_PATH = "resources/omop_cdm_v5_4/OMOP_CDMv5.4_Field_Level.csv"


def test_pinned_specification_is_exempt_from_git_eol_normalization():
    attributes = {
        line.strip()
        for line in (PROJECT_ROOT / ".gitattributes").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert f"{SPEC_GIT_PATH} binary" in attributes


def test_pinned_ohdsi_specification_has_expected_dimensions():
    assert verify_specification()
    specs = load_table_specs()
    assert CDM_RELEASE == "v5.4.3"
    assert len(specs) == 39
    assert sum(map(len, specs.values())) == 432
    assert len(expected_columns("person")) == 18
    assert len(expected_columns("measurement")) == 23


def test_duckdb_ddl_enforces_official_measurement_contract():
    with duckdb.connect(":memory:") as con:
        con.execute(create_table_sql("measurement"))
        assert validate_table_schema(con, "measurement")
        with duckdb.connect(":memory:") as second:
            second.execute(create_table_sql("person"))
            with pytest.raises(duckdb.ConstraintException):
                second.execute("""
                    INSERT INTO person (
                        person_id, gender_concept_id, year_of_birth,
                        race_concept_id, ethnicity_concept_id
                    ) VALUES (1, NULL, 1980, 0, 0)
                """)


def test_schema_installer_is_idempotent_and_records_release(tmp_path):
    db_path = tmp_path / "schema.duckdb"

    setup_cdm_schema(db_path)
    setup_cdm_schema(db_path)

    with duckdb.connect(str(db_path), read_only=True) as con:
        table_count = con.execute("""
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'main'
        """).fetchone()[0]
        manifest = con.execute("""
            SELECT cdm_version, source_release, COUNT(*)
            FROM cdm_schema_manifest
            GROUP BY cdm_version, source_release
        """).fetchone()
    assert table_count == 40
    assert manifest == ("5.4", "v5.4.3", 1)
