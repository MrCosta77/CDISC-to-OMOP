"""Contract validation for the ten SDTM SAS datasets consumed by the ETL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"

REQUIRED_COLUMNS = {
    "dm": {"STUDYID", "USUBJID", "SUBJID", "SITEID", "BRTHDTC", "SEX", "RACE", "RFSTDTC", "RFENDTC"},
    "ae": {"USUBJID", "AESEQ", "AETERM", "AEDECOD", "AESEV", "AESER", "AESTDTC", "AEENDTC"},
    "mh": {"USUBJID", "MHSEQ", "MHTERM", "MHSTDTC"},
    "ex": {"USUBJID", "EXSEQ", "EXTRT", "EXSTDTC", "EXENDTC"},
    "cm": {
        "USUBJID", "CMSEQ", "CMTRT", "CMDECOD", "CMSTDTC", "CMENDTC",
        "CMENRTPT", "CMENTPT",
    },
    "lb": {"USUBJID", "LBSEQ", "VISITNUM", "LBTEST", "LBORRES", "LBORRESU", "LBDTC"},
    "vs": {"USUBJID", "VSSEQ", "VISITNUM", "VSTEST", "VSORRES", "VSORRESU", "VSDTC"},
    "eg": {"USUBJID", "EGSEQ", "VISITNUM", "EGTEST", "EGORRES", "EGORRESU", "EGDTC"},
    "sv": {"USUBJID", "VISITNUM", "VISIT", "SVSTDTC", "SVENDTC"},
    "ds": {"USUBJID", "DSSEQ", "DSTERM", "DSDECOD", "DSSTDTC"},
}

DATE_FIELDS = {
    "dm": ("BRTHDTC", "RFSTDTC", "RFENDTC"),
    "ae": ("AESTDTC", "AEENDTC"),
    "mh": ("MHSTDTC",),
    "ex": ("EXSTDTC", "EXENDTC"),
    "cm": ("CMSTDTC", "CMENDTC", "CMENTPT"),
    "lb": ("LBDTC",),
    "vs": ("VSDTC",),
    "eg": ("EGDTC",),
    "sv": ("SVSTDTC", "SVENDTC"),
    "ds": ("DSSTDTC",),
}

RACE_TERMS = {
    "WHITE",
    "BLACK OR AFRICAN AMERICAN",
    "ASIAN",
    "OTHER",
    "UNKNOWN",
}

NONBLANK_FIELDS = {
    "dm": ("STUDYID", "USUBJID", "SUBJID", "SITEID"),
    "ae": ("USUBJID", "AETERM"),
    "mh": ("USUBJID", "MHTERM"),
    "ex": ("USUBJID", "EXTRT"),
    "cm": ("USUBJID", "CMTRT", "CMDECOD"),
    "lb": ("USUBJID", "LBTEST", "LBORRES"),
    "vs": ("USUBJID", "VSTEST", "VSORRES"),
    "eg": ("USUBJID", "EGTEST", "EGORRES"),
    "sv": ("USUBJID", "VISIT"),
    "ds": ("USUBJID", "DSTERM", "DSDECOD"),
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _nonblank(values: pd.Series) -> pd.Series:
    return values.fillna("").astype(str).str.strip().ne("")


def _parse_dates(frame: pd.DataFrame, domain: str, field: str) -> pd.Series:
    values = frame[field].replace("", pd.NA)
    parsed = pd.to_datetime(values, errors="coerce")
    invalid = values.notna() & parsed.isna()
    _require(not invalid.any(), f"{domain}.{field}: {int(invalid.sum())} invalid date(s)")
    return parsed


def load_sas_inputs(raw_dir: Path = DEFAULT_RAW_DIR) -> dict[str, pd.DataFrame]:
    raw_dir = Path(raw_dir)
    frames = {}
    for domain in REQUIRED_COLUMNS:
        path = raw_dir / f"{domain}.sas7bdat"
        _require(path.is_file(), f"Required SDTM input is missing: {path.name}")
        frames[domain] = pd.read_sas(path, format="sas7bdat", encoding="utf-8")
    return frames


def validate_frames(frames: dict[str, pd.DataFrame]) -> dict[str, int]:
    """Validate in-memory SDTM domains; also used by the versioned golden fixture."""
    missing_domains = sorted(set(REQUIRED_COLUMNS) - set(frames))
    _require(not missing_domains, f"Missing SDTM domain(s): {missing_domains}")

    parsed: dict[tuple[str, str], pd.Series] = {}
    for domain, required in REQUIRED_COLUMNS.items():
        frame = frames[domain]
        missing = sorted(required - set(frame.columns))
        _require(not missing, f"{domain.upper()}: missing required column(s): {missing}")
        _require(not frame.empty, f"{domain.upper()}: dataset is empty")
        for field in NONBLANK_FIELDS[domain]:
            _require(
                _nonblank(frame[field]).all(),
                f"{domain.upper()}.{field}: blank or missing required value",
            )
        for field in DATE_FIELDS[domain]:
            parsed[(domain, field)] = _parse_dates(frame, domain.upper(), field)

    dm = frames["dm"]
    _require(not dm["USUBJID"].duplicated().any(), "DM.USUBJID must be unique")
    _require(set(dm["SEX"].dropna()) <= {"M", "F", "U"}, "DM.SEX contains invalid controlled terminology")
    races = dm["RACE"].fillna("").astype(str).str.strip()
    _require(races.ne("").all(), "DM.RACE is required")
    _require(set(races) <= RACE_TERMS, "DM.RACE contains invalid controlled terminology")
    study_ids = dm["STUDYID"].fillna("").astype(str).str.strip()
    site_ids = dm["SITEID"].fillna("").astype(str).str.strip()
    subjids = dm["SUBJID"].fillna("").astype(str).str.strip()
    _require(study_ids.ne("").all(), "DM.STUDYID is required")
    _require(site_ids.ne("").all(), "DM.SITEID is required")
    _require(subjids.ne("").all(), "DM.SUBJID is required")
    _require(
        (subjids.str.split("-").str[0] == site_ids).all(),
        "DM.SITEID conflicts with SUBJID",
    )
    dm_start = parsed[("dm", "RFSTDTC")]
    dm_end = parsed[("dm", "RFENDTC")]
    _require(dm_start.notna().all() and dm_end.notna().all(), "DM reference dates are required")
    _require((dm_end >= dm_start).all(), "DM.RFENDTC precedes RFSTDTC")
    _require((parsed[("dm", "BRTHDTC")] < dm_start).all(), "DM birth date must precede RFSTDTC")

    subject_ids = set(dm["USUBJID"])
    for domain, frame in frames.items():
        unknown = sorted(set(frame["USUBJID"]) - subject_ids)
        _require(not unknown, f"{domain.upper()}: unknown USUBJID value(s): {unknown[:5]}")
        seq = f"{domain.upper()}SEQ"
        if seq in frame.columns:
            numeric_seq = pd.to_numeric(frame[seq], errors="coerce")
            _require(
                numeric_seq.notna().all(),
                f"{domain.upper()}.{seq}: missing or non-numeric sequence key",
            )
            duplicates = frame.duplicated(["USUBJID", seq], keep=False).sum()
            _require(duplicates == 0, f"{domain.upper()}: duplicate USUBJID/{seq}")

    _require(not frames["sv"].duplicated(["USUBJID", "VISITNUM"]).any(), "SV USUBJID/VISITNUM must be unique")

    visit_numbers = {}
    for domain in ("sv", "lb", "vs", "eg"):
        numbers = pd.to_numeric(frames[domain]["VISITNUM"], errors="coerce")
        _require(
            numbers.notna().all(),
            f"{domain.upper()}.VISITNUM contains missing or non-numeric values",
        )
        visit_numbers[domain] = numbers

    sv_visit_keys = set(
        zip(frames["sv"]["USUBJID"], visit_numbers["sv"].astype(float))
    )
    for domain in ("lb", "vs", "eg"):
        domain_keys = set(
            zip(frames[domain]["USUBJID"], visit_numbers[domain].astype(float))
        )
        unknown_visits = sorted(domain_keys - sv_visit_keys)
        _require(
            not unknown_visits,
            f"{domain.upper()}: VISITNUM reference(s) absent from SV: "
            f"{unknown_visits[:5]}",
        )

    _require(frames["ds"].groupby("USUBJID").size().eq(1).all(), "DS must contain exactly one final record per subject")
    _require(set(frames["ds"]["USUBJID"]) == subject_ids, "DS must cover every DM subject")
    _require(set(frames["ae"]["AESEV"].dropna()) <= {"MILD", "MODERATE", "SEVERE"}, "AE.AESEV contains invalid controlled terminology")
    _require(set(frames["ae"]["AESER"].dropna()) <= {"Y", "N"}, "AE.AESER contains invalid controlled terminology")
    cm_decoded = frames["cm"]["CMDECOD"].fillna("").astype(str).str.strip()
    _require(cm_decoded.ne("").all(), "CM.CMDECOD is required for semantic mapping")
    cm = frames["cm"]
    cm_relative = cm["CMENRTPT"].fillna("").astype(str).str.strip().str.upper()
    _require(
        set(cm_relative) <= {"", "ONGOING"},
        "CM.CMENRTPT contains invalid controlled terminology",
    )
    cm_end = parsed[("cm", "CMENDTC")]
    cm_point = parsed[("cm", "CMENTPT")]
    ongoing = cm_relative.eq("ONGOING")
    _require(
        (cm_end.isna() == ongoing).all(),
        "CM end date and ONGOING indicator are inconsistent",
    )
    _require(
        (cm_point.notna() == ongoing).all(),
        "CM.CMENTPT must be present only for ONGOING records",
    )

    for domain, start_field, end_field in (
        ("ae", "AESTDTC", "AEENDTC"),
        ("ex", "EXSTDTC", "EXENDTC"),
        ("cm", "CMSTDTC", "CMENDTC"),
        ("sv", "SVSTDTC", "SVENDTC"),
    ):
        starts = parsed[(domain, start_field)]
        ends = parsed[(domain, end_field)]
        comparable = ends.notna() & starts.notna()
        _require((ends[comparable] >= starts[comparable]).all(), f"{domain.upper()}: end date precedes start date")

    bounds = pd.DataFrame({"lower": dm_start.values, "upper": dm_end.values}, index=dm["USUBJID"])
    cm_lower = cm["USUBJID"].map(bounds["lower"])
    cm_upper = cm["USUBJID"].map(bounds["upper"])
    _require(
        (
            cm_point[ongoing].reset_index(drop=True)
            >= cm_lower[ongoing].reset_index(drop=True)
        ).all(),
        "CM.CMENTPT precedes RFSTDTC",
    )
    _require(
        (
            cm_point[ongoing].reset_index(drop=True)
            <= cm_upper[ongoing].reset_index(drop=True)
        ).all(),
        "CM.CMENTPT exceeds RFENDTC",
    )
    event_dates = {
        "ae": ("AESTDTC", "AEENDTC"),
        "ex": ("EXSTDTC", "EXENDTC"),
        "lb": ("LBDTC", "LBDTC"),
        "vs": ("VSDTC", "VSDTC"),
        "eg": ("EGDTC", "EGDTC"),
        "sv": ("SVSTDTC", "SVENDTC"),
        "ds": ("DSSTDTC", "DSSTDTC"),
    }
    for domain, (start_field, end_field) in event_dates.items():
        frame = frames[domain]
        starts = parsed[(domain, start_field)]
        ends = parsed[(domain, end_field)].fillna(starts)
        lower = frame["USUBJID"].map(bounds["lower"])
        upper = frame["USUBJID"].map(bounds["upper"])
        _require((starts.reset_index(drop=True) >= lower.reset_index(drop=True)).all(), f"{domain.upper()}: event before RFSTDTC")
        _require((ends.reset_index(drop=True) <= upper.reset_index(drop=True)).all(), f"{domain.upper()}: event after RFENDTC")

    for domain, result_field, unit_field in (
        ("lb", "LBORRES", "LBORRESU"),
        ("vs", "VSORRES", "VSORRESU"),
        ("eg", "EGORRES", "EGORRESU"),
    ):
        frame = frames[domain]
        numeric = pd.to_numeric(frame[result_field], errors="coerce").notna()
        units = frame[unit_field].fillna("").astype(str).str.strip()
        _require(units[numeric].ne("").all(), f"{domain.upper()}: numeric result without source unit")

    return {domain: len(frame) for domain, frame in frames.items()}


def validate_cdisc_inputs(raw_dir: Path = DEFAULT_RAW_DIR) -> dict[str, int]:
    return validate_frames(load_sas_inputs(raw_dir))


def load_golden_fixture(path: Path) -> dict[str, pd.DataFrame]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {domain: pd.DataFrame(records) for domain, records in payload["domains"].items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    args = parser.parse_args()
    counts = validate_cdisc_inputs(args.raw_dir)
    print("CDISC input acceptance passed.")
    for domain, count in sorted(counts.items()):
        print(f" - {domain.upper()}: {count} rows")


if __name__ == "__main__":
    main()
