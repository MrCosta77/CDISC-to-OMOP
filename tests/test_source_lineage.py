import pandas as pd

from src.etl.source_lineage import build_source_lineage


def _write_source(path, target_id, target_value, domain, **extra):
    row = {
        target_id: target_value,
        "person_id": 1,
        "source_domain": domain,
        "source_subject_id": "SUBJ-1",
        "source_record_key": f"{domain}SEQ=1",
        "source_record_value": f"{domain} source",
        "mapping_source_value": f"{domain} mapped",
        **extra,
    }
    pd.DataFrame([row]).to_csv(path, index=False)


def test_source_lineage_covers_each_published_clinical_row(tmp_path):
    _write_source(tmp_path / "PERSON.csv", "person_id", 1, "DM")
    _write_source(
        tmp_path / "OBSERVATION_PERIOD.csv", "observation_period_id", 2, "DM"
    )
    _write_source(
        tmp_path / "VISIT_OCCURRENCE.csv", "visit_occurrence_id", 3, "SV"
    )
    _write_source(
        tmp_path / "CONDITION_OCCURRENCE.csv", "condition_occurrence_id", 4, "AE"
    )
    _write_source(
        tmp_path / "DRUG_EXPOSURE.csv",
        "drug_exposure_id",
        5,
        "CM",
        drug_source_domain="CM",
        drug_mapping_value="ACETAMINOPHEN",
        source_end_date=None,
        published_end_date="2023-01-31",
        end_date_derivation="ADMINISTRATIVE_CENSORING_CMENTPT",
    )
    _write_source(
        tmp_path / "MEASUREMENT.csv",
        "measurement_id",
        6,
        "LB",
        measurement_source_domain="LB",
    )

    lineage = build_source_lineage(
        processed_dir=tmp_path,
        output_path=tmp_path / "SOURCE_RECORD_LINEAGE.csv",
        run_id="RUN-LINEAGE",
    )

    assert len(lineage) == 6
    assert set(lineage["target_table"]) == {
        "person",
        "observation_period",
        "visit_occurrence",
        "condition_occurrence",
        "drug_exposure",
        "measurement",
    }
    drug = lineage[lineage["target_table"] == "drug_exposure"].iloc[0]
    assert drug["source_value"] == "CM source"
    assert drug["mapping_source_value"] == "ACETAMINOPHEN"
    assert drug["source_file"] == "cm.sas7bdat"
    assert drug["published_end_date"] == "2023-01-31"
    assert drug["end_date_derivation"] == "ADMINISTRATIVE_CENSORING_CMENTPT"
