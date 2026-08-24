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
