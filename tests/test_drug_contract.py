import pandas as pd
import pytest

from src.etl.drug import run_drug_etl


def test_missing_source_end_date_uses_start_date(monkeypatch, tmp_path):
    exposure = pd.DataFrame([{
        "USUBJID": "CDISC-01-701-002",
        "EXSEQ": 1,
        "EXSTDTC": "2023-01-10",
        "EXENDTC": None,
        "EXTRT": "Placebo",
        "EXDOSE": 1,
        "EXDOSU": "tablet",
        "EXROUTE": "ORAL",
    }])
    empty_conmeds = pd.DataFrame()
    dm = pd.DataFrame([{
        "USUBJID": "CDISC-01-701-002", "RFENDTC": "2023-04-04"
    }])

    def fake_read_sas(path, **_kwargs):
        if str(path).endswith("ex.sas7bdat"):
            return exposure
        if str(path).endswith("dm.sas7bdat"):
            return dm
        return empty_conmeds

    monkeypatch.setattr(pd, "read_sas", fake_read_sas)
    output_path = tmp_path / "DRUG_EXPOSURE.csv"

    run_drug_etl("ex.sas7bdat", "cm.sas7bdat", output_path)

    result = pd.read_csv(output_path)
    assert result.loc[0, "drug_exposure_start_date"] == "2023-01-10"
    assert result.loc[0, "drug_exposure_end_date"] == "2023-01-10"
    assert result.loc[0, "end_date_derivation"] == "OHDSI_ADMINISTRATION_SAME_DAY"
    assert pd.isna(result.loc[0, "verbatim_end_date"])
    assert result.loc[0, "drug_type_concept_id"] == 32809


def test_cm_uses_decoded_term_for_mapping_and_keeps_verbatim(monkeypatch, tmp_path):
    conmed = pd.DataFrame([{
        "USUBJID": "CDISC-01-701-002",
        "CMSEQ": 1,
        "CMTRT": "Paracetamol",
        "CMDECOD": "ACETAMINOPHEN",
        "CMSTDTC": "2023-01-10",
        "CMENDTC": "2023-01-11",
    }])
    dm = pd.DataFrame([{
        "USUBJID": "CDISC-01-701-002", "RFENDTC": "2023-04-04"
    }])

    def fake_read_sas(path, **_kwargs):
        if str(path).endswith("ex.sas7bdat"):
            return pd.DataFrame()
        if str(path).endswith("dm.sas7bdat"):
            return dm
        return conmed

    monkeypatch.setattr(pd, "read_sas", fake_read_sas)
    output_path = tmp_path / "DRUG_EXPOSURE.csv"
    run_drug_etl("ex.sas7bdat", "cm.sas7bdat", output_path)

    result = pd.read_csv(output_path)
    assert result.loc[0, "drug_source_value"] == "Paracetamol"
    assert result.loc[0, "drug_mapping_value"] == "ACETAMINOPHEN"
    assert result.loc[0, "drug_source_domain"] == "CM"
    assert result.loc[0, "source_record_key"] == "CMSEQ=1"
    assert result.loc[0, "verbatim_end_date"] == "2023-01-11"
    assert result.loc[0, "end_date_derivation"] == "SOURCE_RECORDED"


def test_ongoing_cm_is_administratively_censored_at_rfendtc(monkeypatch, tmp_path):
    conmed = pd.DataFrame([{
        "USUBJID": "CDISC-01-701-002",
        "CMSEQ": 1,
        "CMTRT": "Metformin",
        "CMDECOD": "METFORMIN",
        "CMSTDTC": "2022-12-01",
        "CMENDTC": None,
        "CMENRTPT": "ONGOING",
        "CMENTPT": "2023-03-15",
    }])
    dm = pd.DataFrame([{
        "USUBJID": "CDISC-01-701-002", "RFENDTC": "2023-04-04"
    }])

    def fake_read_sas(path, **_kwargs):
        if str(path).endswith("ex.sas7bdat"):
            return pd.DataFrame()
        if str(path).endswith("dm.sas7bdat"):
            return dm
        return conmed

    monkeypatch.setattr(pd, "read_sas", fake_read_sas)
    output_path = tmp_path / "DRUG_EXPOSURE.csv"
    run_drug_etl("ex.sas7bdat", "cm.sas7bdat", output_path)

    result = pd.read_csv(output_path)
    assert result.loc[0, "drug_exposure_end_date"] == "2023-03-15"
    assert pd.isna(result.loc[0, "verbatim_end_date"])
    assert result.loc[0, "end_date_derivation"] == (
        "ADMINISTRATIVE_CENSORING_CMENTPT"
    )


def test_cm_without_end_or_ongoing_flag_is_rejected(monkeypatch, tmp_path):
    conmed = pd.DataFrame([{
        "USUBJID": "CDISC-01-701-002", "CMSEQ": 1, "CMTRT": "Metformin",
        "CMDECOD": "METFORMIN", "CMSTDTC": "2022-12-01",
        "CMENDTC": None, "CMENRTPT": None,
    }])
    dm = pd.DataFrame([{
        "USUBJID": "CDISC-01-701-002", "RFENDTC": "2023-04-04"
    }])

    def fake_read_sas(path, **_kwargs):
        if str(path).endswith("ex.sas7bdat"):
            return pd.DataFrame()
        if str(path).endswith("dm.sas7bdat"):
            return dm
        return conmed

    monkeypatch.setattr(pd, "read_sas", fake_read_sas)
    with pytest.raises(ValueError, match="not explicitly ONGOING"):
        run_drug_etl("ex.sas7bdat", "cm.sas7bdat", tmp_path / "out.csv")


def test_ongoing_cm_without_cmentpt_is_rejected(monkeypatch, tmp_path):
    conmed = pd.DataFrame([{
        "USUBJID": "CDISC-01-701-002", "CMSEQ": 1, "CMTRT": "Metformin",
        "CMDECOD": "METFORMIN", "CMSTDTC": "2022-12-01",
        "CMENDTC": None, "CMENRTPT": "ONGOING", "CMENTPT": None,
    }])
    dm = pd.DataFrame([{
        "USUBJID": "CDISC-01-701-002", "RFENDTC": "2023-04-04"
    }])

    def fake_read_sas(path, **_kwargs):
        if str(path).endswith("ex.sas7bdat"):
            return pd.DataFrame()
        if str(path).endswith("dm.sas7bdat"):
            return dm
        return conmed

    monkeypatch.setattr(pd, "read_sas", fake_read_sas)
    with pytest.raises(ValueError, match="no valid CMENTPT"):
        run_drug_etl("ex.sas7bdat", "cm.sas7bdat", tmp_path / "out.csv")
