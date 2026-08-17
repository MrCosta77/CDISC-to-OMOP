import pandas as pd
import numpy as np
import hashlib

def generate_person_id(usubjid):
    """
    OMOP requires a numeric person_id (Integer). 
    This function generates a deterministic hash from the USUBJID string.
    """
    if pd.isna(usubjid):
        return np.nan
    # Use MD5 to generate a hash, convert to hex, then to a 32-bit integer
    return int(hashlib.md5(str(usubjid).encode('utf-8')).hexdigest()[:8], 16)

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