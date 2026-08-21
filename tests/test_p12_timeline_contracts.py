import pandas as pd
import pytest

from src.etl.link_visits import run_visit_linking
from src.etl.observation_period import run_observation_period_etl
from src.etl.visit import run_visit_etl
from src.utils.helpers import generate_person_id
from src.utils.run_context import REQUIRED_RAW_DATASETS


USUBJID = "CDISC-01-701-001"


def test_pipeline_requires_sv_and_ds_inputs():
    assert {"sv", "ds"} <= set(REQUIRED_RAW_DATASETS)


def test_observation_period_uses_dm_reference_dates(monkeypatch, tmp_path):
    dm = pd.DataFrame([
        {"USUBJID": USUBJID, "RFSTDTC": "2023-01-10", "RFENDTC": "2023-04-04"}
    ])
    monkeypatch.setattr(pd, "read_sas", lambda *_args, **_kwargs: dm)
    output = tmp_path / "OBSERVATION_PERIOD.csv"
    run_observation_period_etl("dm.sas7bdat", output)
    result = pd.read_csv(output)
    assert result.loc[0, "observation_period_start_date"] == "2023-01-10"
    assert result.loc[0, "observation_period_end_date"] == "2023-04-04"
    assert result.loc[0, "period_type_concept_id"] == 32880


def test_observation_period_rejects_missing_reference_date(monkeypatch, tmp_path):
    dm = pd.DataFrame([
        {"USUBJID": USUBJID, "RFSTDTC": "2023-01-10", "RFENDTC": None}
    ])
    monkeypatch.setattr(pd, "read_sas", lambda *_args, **_kwargs: dm)
    with pytest.raises(ValueError, match="invalid ends: 1"):
        run_observation_period_etl("dm.sas7bdat", tmp_path / "out.csv")


def test_visit_etl_uses_actual_sv_and_crf_provenance(monkeypatch, tmp_path):
    sv = pd.DataFrame([
        {"USUBJID": USUBJID, "VISITNUM": 1, "VISIT": "Visit 1", "SVSTDTC": "2023-01-10", "SVENDTC": "2023-01-10"},
        {"USUBJID": USUBJID, "VISITNUM": 2, "VISIT": "Visit 2", "SVSTDTC": "2023-02-09", "SVENDTC": "2023-02-09"},
    ])
    monkeypatch.setattr(pd, "read_sas", lambda *_args, **_kwargs: sv)
    output = tmp_path / "VISIT_OCCURRENCE.csv"
    run_visit_etl("sv.sas7bdat", output)
    result = pd.read_csv(output)
    assert result["source_visit_num"].tolist() == [1, 2]
    assert result["visit_source_value"].tolist() == ["Visit 1", "Visit 2"]
    assert set(result["visit_type_concept_id"]) == {32809}


def test_visit_etl_rejects_duplicate_subject_visit(monkeypatch, tmp_path):
    row = {"USUBJID": USUBJID, "VISITNUM": 1, "VISIT": "Visit 1", "SVSTDTC": "2023-01-10", "SVENDTC": "2023-01-10"}
    monkeypatch.setattr(pd, "read_sas", lambda *_args, **_kwargs: pd.DataFrame([row, row]))
    with pytest.raises(ValueError, match="duplicate subject/visit numbers: 1"):
        run_visit_etl("sv.sas7bdat", tmp_path / "out.csv")


def _write_link_inputs(directory, visits, condition, drug, measurement):
    visits.to_csv(directory / "VISIT_OCCURRENCE.csv", index=False)
    condition.to_csv(directory / "CONDITION_OCCURRENCE.csv", index=False)
    drug.to_csv(directory / "DRUG_EXPOSURE.csv", index=False)
    measurement.to_csv(directory / "MEASUREMENT.csv", index=False)


def test_visit_linking_prefers_explicit_visit_number(tmp_path):
    person_id = generate_person_id(USUBJID)
    _write_link_inputs(
        tmp_path,
        pd.DataFrame([{"visit_occurrence_id": 10, "person_id": person_id, "visit_start_date": "2023-01-10", "visit_end_date": "2023-01-10", "source_visit_num": 1}]),
        pd.DataFrame([{"person_id": person_id, "condition_start_date": "2020-01-01"}]),
        pd.DataFrame([{"person_id": person_id, "drug_exposure_start_date": "2023-01-11"}]),
        pd.DataFrame([{"person_id": person_id, "measurement_date": "2023-01-11", "source_visit_num": 1}]),
    )
    run_visit_linking(tmp_path)
    measurement = pd.read_csv(tmp_path / "MEASUREMENT.csv")
    condition = pd.read_csv(tmp_path / "CONDITION_OCCURRENCE.csv")
    assert measurement.loc[0, "visit_occurrence_id"] == 10
    assert pd.isna(condition.loc[0, "visit_occurrence_id"])


def test_visit_linking_rejects_ambiguous_date_match(tmp_path):
    person_id = generate_person_id(USUBJID)
    _write_link_inputs(
        tmp_path,
        pd.DataFrame([
            {"visit_occurrence_id": 10, "person_id": person_id, "visit_start_date": "2023-01-10", "visit_end_date": "2023-01-10", "source_visit_num": 1},
            {"visit_occurrence_id": 11, "person_id": person_id, "visit_start_date": "2023-01-10", "visit_end_date": "2023-01-10", "source_visit_num": 2},
        ]),
        pd.DataFrame([{"person_id": person_id, "condition_start_date": "2023-01-10"}]),
        pd.DataFrame(columns=["person_id", "drug_exposure_start_date"]),
        pd.DataFrame(columns=["person_id", "measurement_date"]),
    )
    with pytest.raises(ValueError, match="Ambiguous visit link"):
        run_visit_linking(tmp_path)
