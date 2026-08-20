import pandas as pd
import numpy as np
import hashlib
import re
from datetime import date, datetime


SAS_DATE_EPOCH = pd.Timestamp("1960-01-01")
SAS_DAY_COUNT_PATTERN = re.compile(r"^[+-]?\d+(?:\.0+)?$")

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


def parse_cdisc_date(value):
    """Parse an ISO 8601 DTC value or a numeric SAS date into a Timestamp."""
    if value is None or pd.isna(value):
        return pd.NaT

    if isinstance(value, pd.Timestamp):
        return value

    if isinstance(value, (datetime, date)):
        return pd.Timestamp(value)

    if isinstance(value, (int, float, np.integer, np.floating)):
        if not np.isfinite(value):
            return pd.NaT
        return SAS_DATE_EPOCH + pd.to_timedelta(float(value), unit="D")

    text = str(value).strip()
    if not text:
        return pd.NaT

    # Older EG outputs stored the numeric SAS day count in the character DTC field.
    if SAS_DAY_COUNT_PATTERN.fullmatch(text):
        day_count = float(text)
        if 10000 <= abs(day_count) <= 100000:
            return SAS_DATE_EPOCH + pd.to_timedelta(day_count, unit="D")

    return pd.to_datetime(text, errors="coerce")


def first_numeric_value(row, *columns):
    """Return the first numeric value found in the requested source columns."""
    for column in columns:
        value = row.get(column)
        numeric_value = pd.to_numeric(value, errors="coerce")
        if pd.notna(numeric_value):
            return float(numeric_value)
    return np.nan

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
