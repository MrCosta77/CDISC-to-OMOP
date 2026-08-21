import pandas as pd
import pytest

from src.etl.measurement import run_measurement_etl
from src.utils.helpers import first_numeric_value, parse_cdisc_date


def test_parse_cdisc_date_accepts_iso_and_sas_day_count():
    expected = pd.Timestamp("2023-01-10")

    assert parse_cdisc_date("2023-01-10") == expected
    assert parse_cdisc_date("23020") == expected
    assert parse_cdisc_date(23020) == expected


def test_first_numeric_value_falls_back_to_original_result():
    row = pd.Series({"EGSTRESN": None, "EGORRES": "69"})

    assert first_numeric_value(row, "EGSTRESN", "EGORRES") == 69.0


def test_measurement_etl_recovers_legacy_eg_output(monkeypatch, tmp_path):
    empty_domain = pd.DataFrame()
    legacy_eg = pd.DataFrame(
        [
            {
                "USUBJID": "CDISC-01-701-002",
                "EGDTC": "23020",
                "EGTEST": "Heart Rate",
                "EGORRES": "69",
                "EGORRESU": "beats/min",
            }
        ]
    )

    def fake_read_sas(path, **_kwargs):
        return legacy_eg if str(path).endswith("eg.sas7bdat") else empty_domain

    monkeypatch.setattr(pd, "read_sas", fake_read_sas)
    output_path = tmp_path / "MEASUREMENT.csv"

    run_measurement_etl(
        "lb.sas7bdat", "vs.sas7bdat", "eg.sas7bdat", output_path
    )

    result = pd.read_csv(output_path)
    assert len(result) == 1
    assert result.loc[0, "measurement_date"] == "2023-01-10"
    assert result.loc[0, "value_as_number"] == 69.0
    assert result.loc[0, "measurement_source_domain"] == "EG"
    assert result.loc[0, "measurement_type_concept_id"] == 32809
    assert result.loc[0, "unit_concept_id"] == 8541
    assert result.loc[0, "unit_source_value"] == "beats/min"
    assert result.loc[0, "measurement_source_concept_id"] == 0
    assert result.loc[0, "unit_source_concept_id"] == 0


def test_measurement_etl_rejects_unparseable_eg_date(monkeypatch, tmp_path):
    empty_domain = pd.DataFrame()
    invalid_eg = pd.DataFrame(
        [
            {
                "USUBJID": "CDISC-01-701-002",
                "EGDTC": "not-a-date",
                "EGTEST": "Heart Rate",
                "EGORRES": "69",
                "EGORRESU": "beats/min",
            }
        ]
    )

    def fake_read_sas(path, **_kwargs):
        return invalid_eg if str(path).endswith("eg.sas7bdat") else empty_domain

    monkeypatch.setattr(pd, "read_sas", fake_read_sas)

    with pytest.raises(ValueError, match="Unparseable dates: 1"):
        run_measurement_etl(
            "lb.sas7bdat",
            "vs.sas7bdat",
            "eg.sas7bdat",
            tmp_path / "MEASUREMENT.csv",
        )
