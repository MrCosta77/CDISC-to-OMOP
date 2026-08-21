import pandas as pd
import pytest

from src.etl.condition import run_etl_condition


def test_condition_etl_recovers_legacy_mh_date(monkeypatch, tmp_path):
    empty_ae = pd.DataFrame()
    legacy_mh = pd.DataFrame(
        [
            {
                "USUBJID": "CDISC-01-701-002",
                "MHTERM": "Hyperlipidemia",
                "MHSTDTC": "21758",
            }
        ]
    )

    def fake_read_sas(path, **_kwargs):
        return legacy_mh if str(path).endswith("mh.sas7bdat") else empty_ae

    monkeypatch.setattr(pd, "read_sas", fake_read_sas)
    output_path = tmp_path / "CONDITION_OCCURRENCE.csv"

    run_etl_condition("ae.sas7bdat", "mh.sas7bdat", output_path)

    result = pd.read_csv(output_path)
    assert len(result) == 1
    assert result.loc[0, "condition_start_date"] == "2019-07-28"
    assert result.loc[0, "condition_source_value"] == "Hyperlipidemia"
    assert result.loc[0, "condition_status_source_value"] == "Medical History"


def test_condition_etl_rejects_unparseable_mh_date(monkeypatch, tmp_path):
    empty_ae = pd.DataFrame()
    invalid_mh = pd.DataFrame(
        [
            {
                "USUBJID": "CDISC-01-701-002",
                "MHTERM": "Hyperlipidemia",
                "MHSTDTC": "not-a-date",
            }
        ]
    )

    def fake_read_sas(path, **_kwargs):
        return invalid_mh if str(path).endswith("mh.sas7bdat") else empty_ae

    monkeypatch.setattr(pd, "read_sas", fake_read_sas)

    with pytest.raises(ValueError, match="Unparseable dates: 1"):
        run_etl_condition(
            "ae.sas7bdat",
            "mh.sas7bdat",
            tmp_path / "CONDITION_OCCURRENCE.csv",
        )
