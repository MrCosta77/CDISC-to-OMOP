import pandas as pd

from src.etl.drug import run_drug_etl


def test_missing_source_end_date_uses_start_date(monkeypatch, tmp_path):
    exposure = pd.DataFrame([{
        "USUBJID": "CDISC-01-701-002",
        "EXSTDTC": "2023-01-10",
        "EXENDTC": None,
        "EXTRT": "Placebo",
        "EXDOSE": 1,
        "EXDOSU": "tablet",
        "EXROUTE": "ORAL",
    }])
    empty_conmeds = pd.DataFrame()

    def fake_read_sas(path, **_kwargs):
        return exposure if str(path).endswith("ex.sas7bdat") else empty_conmeds

    monkeypatch.setattr(pd, "read_sas", fake_read_sas)
    output_path = tmp_path / "DRUG_EXPOSURE.csv"

    run_drug_etl("ex.sas7bdat", "cm.sas7bdat", output_path)

    result = pd.read_csv(output_path)
    assert result.loc[0, "drug_exposure_start_date"] == "2023-01-10"
    assert result.loc[0, "drug_exposure_end_date"] == "2023-01-10"
    assert result.loc[0, "drug_type_concept_id"] == 32809
