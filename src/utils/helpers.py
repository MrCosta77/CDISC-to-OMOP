import pandas as pd
import numpy as np
import hashlib

import hashlib

def generate_person_id(usubjid):
    """
    Generates a deterministic, collision-resistant 64-bit integer
    from the CDISC USUBJID using SHA-256.
    """
    if not usubjid:
        return None
    # Use SHA-256 and truncate to 15 hex characters (fits safely in 64-bit int)
    return int(hashlib.sha256(str(usubjid).encode('utf-8')).hexdigest()[:15], 16)

# OMOP Standard Concept IDs Mapping Dictionaries
GENDER_MAP = {
    'M': 8507, # Male
    'F': 8532, # Female
    'U': 8521, # Unknown
}

RACE_MAP = {
    'WHITE': 8527,
    'BLACK OR AFRICAN AMERICAN': 8516,
    'ASIAN': 8515,
    'UNKNOWN': 0
}

ETHNICITY_MAP = {
    'HISPANIC OR LATINO': 38003563,
    'NOT HISPANIC OR LATINO': 38003564,
    'UNKNOWN': 0
}