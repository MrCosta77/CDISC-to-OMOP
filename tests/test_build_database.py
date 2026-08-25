import duckdb
import pandas as pd
import pytest

from src.etl.build_database import (
    build_omop_database,
    validate_published_database,
)
from src.omop.cdm54 import create_table_sql, expected_columns, load_table_specs


PROCESSED_FILES = (
    "CARE_SITE.csv",
    "PERSON.csv",
    "VISIT_OCCURRENCE.csv",
    "CONDITION_OCCURRENCE.csv",
    "DRUG_EXPOSURE.csv",
    "MEASUREMENT.csv",
    "OBSERVATION_PERIOD.csv",
)


def _write_valid_outputs(processed_dir):
    pd.DataFrame({
        "care_site_id": [100],
        "care_site_source_value": ["STUDY|701"],
    }).to_csv(processed_dir / "CARE_SITE.csv", index=False)
    pd.DataFrame({
        "person_id": [1],
        "gender_concept_id": [0],
        "year_of_birth": [1980],
        "race_concept_id": [0],
        "ethnicity_concept_id": [0],
        "care_site_id": [100],
    }).to_csv(processed_dir / "PERSON.csv", index=False)
    pd.DataFrame({
        "observation_period_id": [1],
        "person_id": [1],
        "observation_period_start_date": ["2023-01-01"],
        "observation_period_end_date": ["2023-01-31"],
        "period_type_concept_id": [0],
    }).to_csv(processed_dir / "OBSERVATION_PERIOD.csv", index=False)
    pd.DataFrame({
        "visit_occurrence_id": [10],
        "person_id": [1],
        "visit_concept_id": [0],
        "visit_start_date": ["2023-01-10"],
        "visit_end_date": ["2023-01-10"],
        "visit_type_concept_id": [0],
    }).to_csv(processed_dir / "VISIT_OCCURRENCE.csv", index=False)
    pd.DataFrame({
        "condition_occurrence_id": [20],
        "person_id": [1],
        "condition_concept_id": [0],
        "condition_start_date": ["2023-01-10"],
        "condition_type_concept_id": [0],
        "condition_source_concept_id": [0],
        "visit_occurrence_id": [10],
    }).to_csv(processed_dir / "CONDITION_OCCURRENCE.csv", index=False)
    pd.DataFrame({
        "drug_exposure_id": [30],
        "person_id": [1],
        "drug_concept_id": [0],
        "drug_exposure_start_date": ["2023-01-10"],
        "drug_exposure_end_date": ["2023-01-10"],
        "drug_type_concept_id": [0],
        "drug_source_concept_id": [0],
        "visit_occurrence_id": [10],
    }).to_csv(processed_dir / "DRUG_EXPOSURE.csv", index=False)
    pd.DataFrame({
        "measurement_id": [40],
        "person_id": [1],
        "measurement_concept_id": [0],
        "measurement_date": ["2023-01-10"],
        "measurement_type_concept_id": [0],
        "unit_concept_id": [0],
        "measurement_source_concept_id": [0],
        "unit_source_value": ["custom-unit"],
        "unit_source_concept_id": [0],
        "value_source_value": ["1.0"],
        "visit_occurrence_id": [10],
    }).to_csv(processed_dir / "MEASUREMENT.csv", index=False)
    pd.DataFrame([
        {
            "run_id": "RUN-TEST", "target_table": "person", "target_id": 1,
            "person_id": 1, "source_domain": "DM", "source_file": "dm.sas7bdat",
            "source_subject_id": "SUBJ-1", "source_record_key": "USUBJID=SUBJ-1",
            "source_value": "SUBJ-1", "mapping_source_value": None,
        },
        {
            "run_id": "RUN-TEST", "target_table": "observation_period", "target_id": 1,
            "person_id": 1, "source_domain": "DM", "source_file": "dm.sas7bdat",
            "source_subject_id": "SUBJ-1", "source_record_key": "USUBJID=SUBJ-1",
            "source_value": "SUBJ-1", "mapping_source_value": None,
        },
        {
            "run_id": "RUN-TEST", "target_table": "visit_occurrence", "target_id": 10,
            "person_id": 1, "source_domain": "SV", "source_file": "sv.sas7bdat",
            "source_subject_id": "SUBJ-1", "source_record_key": "VISITNUM=1",
            "source_value": "Visit 1", "mapping_source_value": None,
        },
        {
            "run_id": "RUN-TEST", "target_table": "condition_occurrence", "target_id": 20,
            "person_id": 1, "source_domain": "AE", "source_file": "ae.sas7bdat",
            "source_subject_id": "SUBJ-1", "source_record_key": "AESEQ=1",
            "source_value": "Headache", "mapping_source_value": "HEADACHE",
        },
        {
            "run_id": "RUN-TEST", "target_table": "drug_exposure", "target_id": 30,
            "person_id": 1, "source_domain": "CM", "source_file": "cm.sas7bdat",
            "source_subject_id": "SUBJ-1", "source_record_key": "CMSEQ=1",
            "source_value": "Paracetamol", "mapping_source_value": "ACETAMINOPHEN",
            "source_end_date": None, "published_end_date": "2023-01-31",
            "end_date_derivation": "ADMINISTRATIVE_CENSORING_RFENDTC",
        },
        {
            "run_id": "RUN-TEST", "target_table": "measurement", "target_id": 40,
            "person_id": 1, "source_domain": "LB", "source_file": "lb.sas7bdat",
            "source_subject_id": "SUBJ-1", "source_record_key": "LBSEQ=1",
            "source_value": "Glucose", "mapping_source_value": "Glucose",
        },
    ]).to_csv(processed_dir / "SOURCE_RECORD_LINEAGE.csv", index=False)


def test_database_build_publishes_all_tables(tmp_path):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    _write_valid_outputs(processed_dir)

    db_path = tmp_path / "omop.duckdb"
    build_omop_database(db_path=db_path, processed_dir=processed_dir)

    expected_tables = set(load_table_specs())
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
        for filename in PROCESSED_FILES:
            table = filename.removesuffix(".csv").lower()
            assert con.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0] == 1
        assert [
            row[1]
            for row in con.execute(
                "PRAGMA table_info('measurement')"
            ).fetchall()
        ] == expected_columns("measurement")
        assert con.execute(
            "SELECT COUNT(*) FROM source_record_lineage"
        ).fetchone()[0] == 6
        assert con.execute("""
            SELECT source_end_date, published_end_date, end_date_derivation
            FROM source_record_lineage
            WHERE target_table = 'drug_exposure'
        """).fetchone() == (
            None,
            pd.Timestamp("2023-01-31").date(),
            "ADMINISTRATIVE_CENSORING_RFENDTC",
        )

    with duckdb.connect(str(db_path)) as con:
        with pytest.raises(duckdb.ConstraintException):
            con.execute("""
                INSERT INTO person (
                    person_id, gender_concept_id, year_of_birth,
                    race_concept_id, ethnicity_concept_id
                ) VALUES (1, 0, 1980, 0, 0)
            """)

    acceptance = validate_published_database(db_path)
    assert acceptance["schema_table_count"] == 39
    assert acceptance["row_counts"]["measurement"] == 1
    assert acceptance["extension_counts"]["source_record_lineage"] == 6


def test_incomplete_lineage_rolls_back_publication(tmp_path):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    _write_valid_outputs(processed_dir)
    lineage_path = processed_dir / "SOURCE_RECORD_LINEAGE.csv"
    lineage = pd.read_csv(lineage_path)
    lineage = lineage[lineage["target_table"] != "measurement"]
    lineage.to_csv(lineage_path, index=False)

    db_path = tmp_path / "omop.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute("CREATE TABLE person (person_id BIGINT)")
        con.execute("INSERT INTO person VALUES (7)")

    with pytest.raises(ValueError, match="Lineage coverage failed"):
        build_omop_database(db_path=db_path, processed_dir=processed_dir)

    with duckdb.connect(str(db_path), read_only=True) as con:
        assert con.execute("SELECT person_id FROM person").fetchall() == [(7,)]


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


def test_relational_error_rolls_back_existing_database(tmp_path):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    _write_valid_outputs(processed_dir)
    measurement_path = processed_dir / "MEASUREMENT.csv"
    measurement = pd.read_csv(measurement_path)
    measurement["person_id"] = 999
    measurement.to_csv(measurement_path, index=False)

    db_path = tmp_path / "omop.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute("CREATE TABLE person (person_id BIGINT)")
        con.execute("INSERT INTO person VALUES (7)")

    with pytest.raises(ValueError, match="do not reference"):
        build_omop_database(db_path=db_path, processed_dir=processed_dir)

    with duckdb.connect(str(db_path), read_only=True) as con:
        assert con.execute("SELECT person_id FROM person").fetchall() == [(7,)]


def test_unknown_person_care_site_aborts_publication(tmp_path):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    _write_valid_outputs(processed_dir)
    person_path = processed_dir / "PERSON.csv"
    person = pd.read_csv(person_path)
    person["care_site_id"] = 999
    person.to_csv(person_path, index=False)

    with pytest.raises(ValueError, match="do not reference"):
        build_omop_database(
            db_path=tmp_path / "omop.duckdb",
            processed_dir=processed_dir,
        )


def test_required_omop_value_is_not_silently_published(tmp_path):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    _write_valid_outputs(processed_dir)
    drug_path = processed_dir / "DRUG_EXPOSURE.csv"
    drug = pd.read_csv(drug_path)
    drug["drug_exposure_end_date"] = None
    drug.to_csv(drug_path, index=False)

    with pytest.raises(duckdb.ConstraintException):
        build_omop_database(
            db_path=tmp_path / "omop.duckdb",
            processed_dir=processed_dir,
        )


def test_missing_source_semantics_abort_publication(tmp_path):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    _write_valid_outputs(processed_dir)
    measurement_path = processed_dir / "MEASUREMENT.csv"
    measurement = pd.read_csv(measurement_path).drop(columns=["unit_concept_id"])
    measurement.to_csv(measurement_path, index=False)

    with pytest.raises(ValueError, match="source-semantic fields"):
        build_omop_database(
            db_path=tmp_path / "omop.duckdb",
            processed_dir=processed_dir,
        )


def test_wrong_domain_unit_concept_aborts_publication(tmp_path):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    _write_valid_outputs(processed_dir)
    measurement_path = processed_dir / "MEASUREMENT.csv"
    measurement = pd.read_csv(measurement_path)
    measurement["unit_concept_id"] = 999001
    measurement.to_csv(measurement_path, index=False)

    db_path = tmp_path / "omop.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute(create_table_sql("concept"))
        con.execute("""
            INSERT INTO concept (
                concept_id, concept_name, domain_id, vocabulary_id,
                concept_class_id, standard_concept, concept_code,
                valid_start_date, valid_end_date
            ) VALUES (999001, 'Not a unit', 'Measurement', 'LOINC',
                      'Lab Test', 'S', 'X', '1970-01-01', '2099-12-31')
        """)

    with pytest.raises(
        ValueError, match="invalid or wrong-domain Standard Concepts"
    ):
        build_omop_database(db_path=db_path, processed_dir=processed_dir)


def test_visit_outside_observation_period_aborts_publication(tmp_path):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    _write_valid_outputs(processed_dir)
    visit_path = processed_dir / "VISIT_OCCURRENCE.csv"
    visit = pd.read_csv(visit_path)
    visit["visit_start_date"] = "2023-02-01"
    visit["visit_end_date"] = "2023-02-01"
    visit.to_csv(visit_path, index=False)

    with pytest.raises(ValueError, match="visits fall outside"):
        build_omop_database(
            db_path=tmp_path / "omop.duckdb",
            processed_dir=processed_dir,
        )


def test_event_linked_outside_visit_aborts_publication(tmp_path):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    _write_valid_outputs(processed_dir)
    condition_path = processed_dir / "CONDITION_OCCURRENCE.csv"
    conditions = pd.read_csv(condition_path)
    conditions.loc[0, "condition_start_date"] = "2023-02-11"
    conditions.to_csv(condition_path, index=False)

    with pytest.raises(ValueError, match="Visit-link validation failed"):
        build_omop_database(
            db_path=tmp_path / "omop.duckdb",
            processed_dir=processed_dir,
        )


@pytest.mark.parametrize(
    ("concept_id", "standard_concept", "valid_end_date"),
    [
        (32020, None, "2099-12-31"),
        (32809, "S", "2020-12-31"),
    ],
)
def test_invalid_type_concept_aborts_publication(
    tmp_path, concept_id, standard_concept, valid_end_date
):
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    _write_valid_outputs(processed_dir)
    condition_path = processed_dir / "CONDITION_OCCURRENCE.csv"
    condition = pd.read_csv(condition_path)
    condition["condition_type_concept_id"] = concept_id
    condition.to_csv(condition_path, index=False)

    db_path = tmp_path / "omop.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute(create_table_sql("concept"))
        con.execute(
            """
            INSERT INTO concept (
                concept_id, concept_name, domain_id, vocabulary_id,
                concept_class_id, standard_concept, concept_code,
                valid_start_date, valid_end_date
            ) VALUES (?, 'Test type', 'Type Concept', 'Type Concept',
                      'Type Concept', ?, 'Test', '1970-01-01', ?)
            """,
            [concept_id, standard_concept, valid_end_date],
        )

    with pytest.raises(
        ValueError, match="invalid or wrong-domain Standard Concepts"
    ):
        build_omop_database(db_path=db_path, processed_dir=processed_dir)
