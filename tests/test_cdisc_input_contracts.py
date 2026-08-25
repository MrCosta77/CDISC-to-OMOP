from pathlib import Path

import pytest

from src.quality.validate_cdisc_inputs import load_golden_fixture, validate_frames


GOLDEN = Path(__file__).parent / "fixtures" / "golden_cdisc.json"


def _frames():
    return load_golden_fixture(GOLDEN)


def test_golden_cdisc_domains_pass_the_common_input_contract():
    counts = validate_frames(_frames())
    assert counts == {domain: 1 for domain in ("dm", "ae", "mh", "ex", "cm", "lb", "vs", "eg", "sv", "ds")}


def test_unknown_subject_is_rejected():
    frames = _frames()
    frames["ae"].loc[0, "USUBJID"] = "MISSING"
    with pytest.raises(ValueError, match="unknown USUBJID"):
        validate_frames(frames)


def test_invalid_race_term_is_rejected():
    frames = _frames()
    frames["dm"].loc[0, "RACE"] = "BLACK"
    with pytest.raises(ValueError, match="RACE contains invalid"):
        validate_frames(frames)


def test_site_must_be_present_and_match_subjid():
    frames = _frames()
    frames["dm"].loc[0, "SITEID"] = "999"
    with pytest.raises(ValueError, match="SITEID conflicts"):
        validate_frames(frames)


def test_blank_site_is_rejected():
    frames = _frames()
    frames["dm"].loc[0, "SITEID"] = ""
    with pytest.raises(ValueError, match="SITEID is required"):
        validate_frames(frames)


def test_numeric_measurement_requires_source_unit():
    frames = _frames()
    frames["eg"].loc[0, "EGORRESU"] = ""
    with pytest.raises(ValueError, match="numeric result without source unit"):
        validate_frames(frames)


def test_event_outside_reference_period_is_rejected():
    frames = _frames()
    frames["sv"].loc[0, "SVSTDTC"] = "2024-12-31"
    frames["sv"].loc[0, "SVENDTC"] = "2024-12-31"
    with pytest.raises(ValueError, match="event before RFSTDTC"):
        validate_frames(frames)


def test_ongoing_cm_requires_an_explicit_assessment_point():
    frames = _frames()
    frames["cm"].loc[0, "CMENTPT"] = ""
    with pytest.raises(ValueError, match="CMENTPT must be present"):
        validate_frames(frames)


def test_cm_assessment_point_must_be_inside_dm_reference_period():
    frames = _frames()
    frames["cm"].loc[0, "CMENTPT"] = "2025-04-01"
    with pytest.raises(ValueError, match="CMENTPT exceeds RFENDTC"):
        validate_frames(frames)


def test_nonongoing_cm_must_not_carry_a_reference_point():
    frames = _frames()
    frames["cm"].loc[0, "CMENDTC"] = "2025-02-01"
    frames["cm"].loc[0, "CMENRTPT"] = ""
    with pytest.raises(ValueError, match="CMENTPT must be present only"):
        validate_frames(frames)


@pytest.mark.parametrize("domain", ["lb", "vs", "eg"])
def test_measurement_visit_number_must_exist_in_sv(domain):
    frames = _frames()
    frames[domain].loc[0, "VISITNUM"] = 99
    with pytest.raises(ValueError, match="VISITNUM reference.*absent from SV"):
        validate_frames(frames)
