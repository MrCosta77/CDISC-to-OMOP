import pytest

from src.omop.type_concepts import (
    CASE_REPORT_FORM,
    STANDARD_ALGORITHM,
    TYPE_CONCEPT_ASSIGNMENTS,
    TYPE_CONCEPT_FIELDS,
    required_type_concepts,
    type_concept_for,
    type_concept_id_for,
)


DIRECT_SOURCES = {
    ("condition_occurrence", "AE"),
    ("condition_occurrence", "MH"),
    ("drug_exposure", "EX"),
    ("drug_exposure", "CM"),
    ("measurement", "LB"),
    ("measurement", "VS"),
    ("measurement", "EG"),
    ("visit_occurrence", "SV"),
}
DERIVED_SOURCES = {
    ("observation_period", "DERIVED"),
}


def test_type_concept_matrix_is_complete_and_avoids_ehr_provenance():
    actual_sources = {
        (assignment.target_table, assignment.source_domain)
        for assignment in TYPE_CONCEPT_ASSIGNMENTS
    }
    assert actual_sources == DIRECT_SOURCES | DERIVED_SOURCES
    assert {
        type_concept_id_for(table, source)
        for table, source in DIRECT_SOURCES
    } == {CASE_REPORT_FORM}
    assert {
        type_concept_id_for(table, source)
        for table, source in DERIVED_SOURCES
    } == {STANDARD_ALGORITHM}
    assert required_type_concepts() == {
        32809: "Case Report Form",
        32880: "Standard algorithm",
    }


def test_every_published_type_field_has_a_documented_assignment():
    assert set(TYPE_CONCEPT_FIELDS) == {
        assignment.target_table for assignment in TYPE_CONCEPT_ASSIGNMENTS
    }
    assert type_concept_for("MEASUREMENT", "eg").concept_id == 32809


def test_unknown_source_requires_an_explicit_decision():
    with pytest.raises(ValueError, match="No OMOP Type Concept is documented"):
        type_concept_id_for("measurement", "CENTRAL_LAB")
