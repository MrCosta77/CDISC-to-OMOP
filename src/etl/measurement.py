import pandas as pd
import numpy as np
import sys
import os

# Add the src directory to the python path to import utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.utils.helpers import first_numeric_value, generate_person_id, parse_cdisc_date

def run_measurement_etl(lb_path, vs_path, eg_path, output_path):
    """
    Extracts Laboratory (LB), Vital Signs (VS), and ECG (EG) data 
    and transforms them into a unified OMOP MEASUREMENT table.
    """
    measurement_records = []
    measurement_id_counter = 1

    # ---------------------------------------------------------
    # 1. PROCESS LABORATORY RESULTS (LB)
    # ---------------------------------------------------------
    print(f"🔬 Reading CDISC Laboratory Results from: {lb_path}")
    try:
        df_lb = pd.read_sas(lb_path, format="sas7bdat", encoding="utf-8")
        
        for _, row in df_lb.iterrows():
            obs_date = parse_cdisc_date(row.get('LBDTC'))
            
            measurement_records.append({
                'measurement_id': measurement_id_counter,
                'person_id': generate_person_id(row.get('USUBJID')),
                'measurement_concept_id': 0, # Pending AI Mapping (e.g., LOINC)
                'measurement_type_concept_id': 32838, # OMOP standard for "Clinical Study Observation"
                'measurement_date': obs_date.date() if pd.notna(obs_date) else np.nan,
                'measurement_datetime': obs_date if pd.notna(obs_date) else pd.NaT,
                'value_as_number': first_numeric_value(row, 'LBSTRESN', 'LBORRES'),
                'value_source_value': row.get('LBORRES'),
                'unit_source_value': row.get('LBORRESU'),
                'measurement_source_value': row.get('LBTEST'),
                'measurement_source_domain': 'LB' # Custom traceability
            })
            measurement_id_counter += 1
    except FileNotFoundError:
        print(f"⚠️ Warning: File '{lb_path}' not found. Skipping LB domain.")

    # ---------------------------------------------------------
    # 2. PROCESS VITAL SIGNS (VS)
    # ---------------------------------------------------------
    print(f"🩺 Reading CDISC Vital Signs from: {vs_path}")
    try:
        df_vs = pd.read_sas(vs_path, format="sas7bdat", encoding="utf-8")
        
        for _, row in df_vs.iterrows():
            obs_date = parse_cdisc_date(row.get('VSDTC'))
            
            measurement_records.append({
                'measurement_id': measurement_id_counter,
                'person_id': generate_person_id(row.get('USUBJID')),
                'measurement_concept_id': 0, 
                'measurement_type_concept_id': 32838, 
                'measurement_date': obs_date.date() if pd.notna(obs_date) else np.nan,
                'measurement_datetime': obs_date if pd.notna(obs_date) else pd.NaT,
                'value_as_number': first_numeric_value(row, 'VSSTRESN', 'VSORRES'),
                'value_source_value': row.get('VSORRES'),
                'unit_source_value': row.get('VSORRESU'),
                'measurement_source_value': row.get('VSTEST'),
                'measurement_source_domain': 'VS'
            })
            measurement_id_counter += 1
    except FileNotFoundError:
        print(f"⚠️ Warning: File '{vs_path}' not found. Skipping VS domain.")

    # ---------------------------------------------------------
    # 3. PROCESS ECG RESULTS (EG)
    # ---------------------------------------------------------
    print(f"🫀 Reading CDISC ECG Results from: {eg_path}")
    try:
        df_eg = pd.read_sas(eg_path, format="sas7bdat", encoding="utf-8")

        required_columns = {'USUBJID', 'EGDTC', 'EGTEST', 'EGORRES', 'EGORRESU'}
        missing_columns = sorted(required_columns.difference(df_eg.columns))
        if missing_columns:
            raise ValueError(
                "EG data contract violation. Missing required columns: "
                + ", ".join(missing_columns)
            )

        df_eg = df_eg.copy()
        df_eg['_parsed_date'] = df_eg['EGDTC'].apply(parse_cdisc_date)
        df_eg['_numeric_result'] = df_eg.apply(
            lambda row: first_numeric_value(row, 'EGSTRESN', 'EGORRES'), axis=1
        )

        invalid_dates = int(df_eg['_parsed_date'].isna().sum())
        invalid_results = int(df_eg['_numeric_result'].isna().sum())
        if invalid_dates or invalid_results:
            raise ValueError(
                "EG data contract violation. "
                f"Unparseable dates: {invalid_dates}; non-numeric results: {invalid_results}."
            )
        
        for _, row in df_eg.iterrows():
            obs_date = row['_parsed_date']
            
            measurement_records.append({
                'measurement_id': measurement_id_counter,
                'person_id': generate_person_id(row.get('USUBJID')),
                'measurement_concept_id': 0, 
                'measurement_type_concept_id': 32838, 
                'measurement_date': obs_date.date() if pd.notna(obs_date) else np.nan,
                'measurement_datetime': obs_date if pd.notna(obs_date) else pd.NaT,
                'value_as_number': row['_numeric_result'],
                'value_source_value': row.get('EGORRES'),
                'unit_source_value': row.get('EGORRESU'),
                'measurement_source_value': row.get('EGTEST'),
                'measurement_source_domain': 'EG'
            })
            measurement_id_counter += 1
    except FileNotFoundError:
        print(f"⚠️ Warning: File '{eg_path}' not found. Skipping EG domain.")

    # ---------------------------------------------------------
    # 4. BUILD AND EXPORT
    # ---------------------------------------------------------
    if not measurement_records:
        print("❌ Error: No measurement records found to process.")
        return

    print("\nMerging domains and building OMOP MEASUREMENT table...")
    df_measurement = pd.DataFrame(measurement_records)

    # Clean integers
    integer_cols = ['measurement_id', 'person_id', 'measurement_concept_id', 'measurement_type_concept_id']
    for col in integer_cols:
        df_measurement[col] = df_measurement[col].astype('Int64')

    print(f"✅ MEASUREMENT table generated successfully with {len(df_measurement)} records!")
    print(df_measurement[['measurement_id', 'measurement_source_domain', 'measurement_source_value', 'value_as_number', 'unit_source_value']].head())

    df_measurement.to_csv(output_path, index=False)
    print(f"File saved to: {output_path}")

if __name__ == "__main__":
    LB_FILE = "data/raw/lb.sas7bdat"
    VS_FILE = "data/raw/vs.sas7bdat"
    EG_FILE = "data/raw/eg.sas7bdat"
    OUTPUT_FILE = "data/processed/MEASUREMENT.csv"
    
    run_measurement_etl(LB_FILE, VS_FILE, EG_FILE, OUTPUT_FILE)
