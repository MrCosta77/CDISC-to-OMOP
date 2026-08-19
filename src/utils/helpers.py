import pandas as pd
import numpy as np
import hashlib

def generate_person_id(usubjid):
    """
    Generates a deterministic, collision-resistant 64-bit integer
    from the CDISC USUBJID using SHA-256.
    """
    # 1. Catch Pandas NA, NaT, None, or numpy NaN cleanly
    if pd.isna(usubjid):
        return None
        
    # 2. Convert to string and catch empty strings or literal 'nan'
    clean_id = str(usubjid).strip()
    if not clean_id or clean_id.lower() == 'nan':
        return None
        
    # 3. Secure Hash
    return int(hashlib.sha256(clean_id.encode('utf-8')).hexdigest()[:15], 16)

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