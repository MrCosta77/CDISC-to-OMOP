"""Documented OMOP Type Concept assignments for the CDISC pipeline."""

from dataclasses import dataclass


CASE_REPORT_FORM = 32809
STANDARD_ALGORITHM = 32880


@dataclass(frozen=True)
class TypeConceptAssignment:
    target_table: str
    source_domain: str
    concept_id: int
    concept_name: str
    rationale: str


TYPE_CONCEPT_FIELDS = {
    "observation_period": "period_type_concept_id",
    "visit_occurrence": "visit_type_concept_id",
    "condition_occurrence": "condition_type_concept_id",
    "drug_exposure": "drug_type_concept_id",
    "measurement": "measurement_type_concept_id",
}


TYPE_CONCEPT_ASSIGNMENTS = (
    TypeConceptAssignment(
        "condition_occurrence",
        "AE",
        CASE_REPORT_FORM,
        "Case Report Form",
        "Adverse Events are reported in the trial eCRF and tabulated in SDTM AE.",
    ),
    TypeConceptAssignment(
        "condition_occurrence",
        "MH",
        CASE_REPORT_FORM,
        "Case Report Form",
        "Medical History is collected in the trial eCRF and tabulated in SDTM MH.",
    ),
    TypeConceptAssignment(
        "drug_exposure",
        "EX",
        CASE_REPORT_FORM,
        "Case Report Form",
        "Study exposure is captured for the trial and tabulated in SDTM EX.",
    ),
    TypeConceptAssignment(
        "drug_exposure",
        "CM",
        CASE_REPORT_FORM,
        "Case Report Form",
        "Concomitant medication is collected in the eCRF and tabulated in SDTM CM.",
    ),
    TypeConceptAssignment(
        "measurement",
        "LB",
        CASE_REPORT_FORM,
        "Case Report Form",
        "The current synthetic LB feed is treated as an eCRF/SDTM source.",
    ),
    TypeConceptAssignment(
        "measurement",
        "VS",
        CASE_REPORT_FORM,
        "Case Report Form",
        "Vital signs are collected for the trial and tabulated in SDTM VS.",
    ),
    TypeConceptAssignment(
        "measurement",
        "EG",
        CASE_REPORT_FORM,
        "Case Report Form",
        "ECG results are collected for the trial and tabulated in SDTM EG.",
    ),
    TypeConceptAssignment(
        "visit_occurrence",
        "DERIVED",
        STANDARD_ALGORITHM,
        "Standard algorithm",
        "Visits are derived deterministically from distinct event dates.",
    ),
    TypeConceptAssignment(
        "observation_period",
        "DERIVED",
        STANDARD_ALGORITHM,
        "Standard algorithm",
        "Observation periods are derived from DM reference dates or active events.",
    ),
)


_ASSIGNMENTS_BY_SOURCE = {
    (assignment.target_table, assignment.source_domain): assignment
    for assignment in TYPE_CONCEPT_ASSIGNMENTS
}
if len(_ASSIGNMENTS_BY_SOURCE) != len(TYPE_CONCEPT_ASSIGNMENTS):
    raise ValueError("Duplicate CDISC Type Concept assignment.")


def type_concept_for(target_table, source_domain):
    """Return the documented Type Concept assignment for a source domain."""
    key = (str(target_table).strip().lower(), str(source_domain).strip().upper())
    try:
        return _ASSIGNMENTS_BY_SOURCE[key]
    except KeyError as exc:
        raise ValueError(
            "No OMOP Type Concept is documented for "
            f"{key[0]}/{key[1]}."
        ) from exc


def type_concept_id_for(target_table, source_domain):
    return type_concept_for(target_table, source_domain).concept_id


def required_type_concepts():
    """Return the unique Concept IDs and names required by this pipeline."""
    return {
        assignment.concept_id: assignment.concept_name
        for assignment in TYPE_CONCEPT_ASSIGNMENTS
    }
