import pandas as pd

from src.omop.unit_concepts import unit_concept_id_for


def test_known_cdisc_unit_maps_to_standard_unit_concept():
    assert unit_concept_id_for("mg/dL") == 8840
    assert unit_concept_id_for("beats/min") == 8541


def test_present_unknown_unit_maps_to_zero():
    assert unit_concept_id_for("custom-unit") == 0


def test_absent_unit_remains_null():
    assert pd.isna(unit_concept_id_for(None))
    assert pd.isna(unit_concept_id_for(""))
