import pandas as pd
import numpy as np
import sys
import os

# Add the src directory to the python path to import utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.utils.helpers import generate_person_id

def run_etl_condition(input_path, output_path):
    """
    Extracts Adverse Events data (ae.sas7bdat) and transforms it into the OMOP CONDITION_OCCURRENCE table.
    """
    print(f"Reading CDISC Adverse Events file from: {input_path}")
    try:
        df_ae = pd.read_sas(input_path, format="sas7bdat", encoding="utf-8")
    except FileNotFoundError:
        print(f"Error: File '{input_path}' not found. Please ensure it is in the data/raw/ folder.")
        return

    print("Starting transformation to OMOP CONDITION_OCCURRENCE table...")
    condition_records = []

    # We will need an artificial condition_occurrence_id (Primary Key)
    # Using a simple counter for now, but in a real DB this would be auto-incremented
    condition_id_counter = 1

    for _, row in df_ae.iterrows():
        # Parse dates (assuming ISO8601 YYYY-MM-DD in AESTDTC and AEENDTC)
        start_date = pd.to_datetime(row.get('AESTDTC'), errors='coerce')
        end_date = pd.to_datetime(row.get('AEENDTC'), errors='coerce')
        
        # Extract the raw clinical term (AETERM) or decoded dictionary term (AEDECOD)
        # We prioritize AETERM as the pure source value from the clinical trial
        source_value = row.get('AETERM')
        if pd.isna(source_value):
            source_value = row.get('AEDECOD')

        condition = {
            'condition_occurrence_id': condition_id_counter,
            
            # Crucial: Linking back to the patient using our deterministic hash
            'person_id': generate_person_id(row.get('USUBJID')),
            
            # Concept IDs (Set to 0 for now - we will map this later using the LLM agent)
            'condition_concept_id': 0, 
            
            # Type Concept ID is mandatory in OMOP. 
            # 32020 represents "EHR encounter diagnosis" (Standard placeholder)
            'condition_type_concept_id': 32020, 
            
            # Dates
            'condition_start_date': start_date.date() if pd.notna(start_date) else np.nan,
            'condition_start_datetime': start_date if pd.notna(start_date) else pd.NaT,
            'condition_end_date': end_date.date() if pd.notna(end_date) else np.nan,
            'condition_end_datetime': end_date if pd.notna(end_date) else pd.NaT,
            
            # Traceability
            'condition_source_value': source_value,
            'condition_status_source_value': row.get('AEOUT') # Outcome of the AE
        }
        condition_records.append(condition)
        condition_id_counter += 1

    # Create OMOP DataFrame
    df_condition = pd.DataFrame(condition_records)

    # Ensure integer columns are cast correctly (avoids floats/decimals)
    integer_cols = ['condition_occurrence_id', 'person_id', 'condition_concept_id', 'condition_type_concept_id']
    for col in integer_cols:
        df_condition[col] = df_condition[col].astype('Int64')

    print("CONDITION_OCCURRENCE table successfully generated!")
    
    # Print a small preview to terminal
    print(df_condition[['condition_occurrence_id', 'person_id', 'condition_start_date', 'condition_source_value']].head())

    # Export to processed data folder
    df_condition.to_csv(output_path, index=False)
    print(f"File saved to: {output_path}")

if __name__ == "__main__":
    INPUT_FILE = "data/raw/ae.sas7bdat"
    OUTPUT_FILE = "data/processed/CONDITION_OCCURRENCE.csv"
    
    run_etl_condition(INPUT_FILE, OUTPUT_FILE)