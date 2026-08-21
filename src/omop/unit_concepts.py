"""Auditable CDISC unit mappings to OMOP Standard Unit Concepts."""

import pandas as pd


# Source spelling -> OMOP Standard Unit concept_id.
# The source value is preserved separately in unit_source_value.
STANDARD_UNIT_CONCEPTS = {
    "MG/DL": 8840,
    "mg/dL": 8840,
    "U/L": 8645,
    "beats/min": 8541,
    "g/dL": 8713,
    "kg": 9529,
    "mmHg": 8876,
    "msec": 9593,
}


def unit_concept_id_for(source_unit):
    """Return NULL for absent units, 0 for unmapped units, or a Standard ID."""
    if source_unit is None or pd.isna(source_unit):
        return pd.NA
    source_unit = str(source_unit).strip()
    if not source_unit:
        return pd.NA
    return STANDARD_UNIT_CONCEPTS.get(source_unit, 0)
