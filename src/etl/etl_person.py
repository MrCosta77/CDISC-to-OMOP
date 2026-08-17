import pandas as pd
import numpy as np
import sys
import os

# Add the src directory to the python path to import utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.utils.helpers import generate_person_id, GENDER_MAP, RACE_MAP, ETHNICITY_MAP

def run_etl_person(input_path, output_path):
    """
    Extracts demographics data (dm.sas7bdat) and transforms it into the OMOP PERSON table.
    """
    print(f"Reading CDISC Demographics file from: {input_path}")
    try:
        # pyreadstat is used under the hood by pandas to read sas7bdat
        df_dm = pd.read_sas(input_path, format="sas7bdat", encoding="utf-8")
    except FileNotFoundError:
        print(f"Error: File '{input_path}' not found. Please ensure it is in the data/raw/ folder.")
        return

    print("Starting transformation to OMOP PERSON table...")
    person_records = []

    for _, row in df_dm.iterrows():
        # Parse birth date (assuming ISO8601 YYYY-MM-DD in BRTHDTC)
        birth_date = pd.to_datetime(row.get('BRTHDTC'), errors='coerce')
        
        person = {
            'person_id': generate_person_id(row.get('USUBJID')),
            'gender_concept_id': GENDER_MAP.get(row.get('SEX'), 0),
            'year_of_birth': birth_date.year if pd.notna(birth_date) else np.nan,
            'month_of_birth': birth_date.month if pd.notna(birth_date) else np.nan,
            'day_of_birth': birth_date.day if pd.notna(birth_date) else np.nan,
            'birth_datetime': birth_date if pd.notna(birth_date) else pd.NaT,
            'race_concept_id': RACE_MAP.get(str(row.get('RACE')).upper(), 0),
            'ethnicity_concept_id': ETHNICITY_MAP.get(str(row.get('ETHNIC')).upper(), 0),
            
            # Traceability (Source values are critical in RWE)
            'person_source_value': row.get('USUBJID'),
            'gender_source_value': row.get('SEX'),
            'race_source_value': row.get('RACE'),
            'ethnicity_source_value': row.get('ETHNIC')
        }
        person_records.append(person)

    # Create OMOP DataFrame
    df_person = pd.DataFrame(person_records)

    # Ensure person_id and year_of_birth are Int64 (avoids floats/decimals for missing values)
    df_person['person_id'] = df_person['person_id'].astype('Int64')
    df_person['year_of_birth'] = df_person['year_of_birth'].astype('Int64')

    print("PERSON table successfully generated!")
    print(df_person.head())

    # Export to processed data folder
    df_person.to_csv(output_path, index=False)
    print(f"File saved to: {output_path}")

if __name__ == "__main__":
    # Define file paths relative to the project root
    INPUT_FILE = "data/raw/dm.sas7bdat"
    OUTPUT_FILE = "data/processed/PERSON.csv"
    
    run_etl_person(INPUT_FILE, OUTPUT_FILE)