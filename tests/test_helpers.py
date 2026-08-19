import pytest
import pandas as pd
import sys
from pathlib import Path

# Setup paths to allow importing from the src/ folder
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.utils.helpers import generate_person_id

def test_generate_person_id_determinism():
    """Test if the same USUBJID always generates the exact same integer ID."""
    usubjid = "CDISC-01-701-001"
    id1 = generate_person_id(usubjid)
    id2 = generate_person_id(usubjid)
    
    assert id1 == id2, "Determinism failed: Same input generated different IDs"
    assert isinstance(id1, int), "Type failed: Generated ID is not an integer"

def test_generate_person_id_collision():
    """Test if different USUBJIDs generate different IDs."""
    id1 = generate_person_id("CDISC-01-701-001")
    id2 = generate_person_id("CDISC-01-701-002")
    
    assert id1 != id2, "Collision detected: Different inputs generated the same ID"

def test_generate_person_id_null_handling():
    """Test if null, None, or empty strings are safely handled and return None."""
    assert generate_person_id(None) is None, "Failed to handle None"
    assert generate_person_id("") is None, "Failed to handle empty string"
    assert generate_person_id(pd.NA) is None, "Failed to handle pandas NA"

def test_generate_person_id_bigint_bounds():
    """
    Test if the generated ID fits safely within an OMOP 64-bit BIGINT.
    Maximum PostgreSQL/DuckDB BIGINT is 9,223,372,036,854,775,807.
    """
    max_bigint = 9223372036854775807
    generated_id = generate_person_id("EXTREMELY_LONG_USUBJID_FOR_A_CLINICAL_TRIAL_PATIENT_999")
    
    assert generated_id > 0, "Generated ID must be strictly positive"
    assert generated_id <= max_bigint, f"ID {generated_id} exceeds 64-bit maximum"