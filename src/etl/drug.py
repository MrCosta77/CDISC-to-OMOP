import pandas as pd
import numpy as np
import sys
import os

# Add the src directory to the python path to import utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.utils.helpers import generate_person_id

def run_drug_etl(ex_path, cm_path, output_path):
    """
    Extracts Exposure (EX) and Concomitant Medications (CM) data 
    and transforms them into a unified OMOP DRUG_EXPOSURE table.
    """
    drug_records = []
    drug_id_counter = 1

    # ---------------------------------------------------------
    # 1. PROCESS STUDY DRUGS (EX)
    # ---------------------------------------------------------
    print(f"💊 Reading CDISC Exposure (Study Drugs) from: {ex_path}")
    try:
        df_ex = pd.read_sas(ex_path, format="sas7bdat", encoding="utf-8")
        
        for _, row in df_ex.iterrows():
            start_date = pd.to_datetime(row.get('EXSTDTC'), errors='coerce')
            end_date = pd.to_datetime(row.get('EXENDTC'), errors='coerce')
            
            drug_records.append({
                'drug_exposure_id': drug_id_counter,
                'person_id': generate_person_id(row.get('USUBJID')),
                'drug_concept_id': 0, # Pending AI Mapping to RxNorm
                'drug_type_concept_id': 32838, # OMOP standard for "Clinical Study Observation"
                'drug_exposure_start_date': start_date.date() if pd.notna(start_date) else np.nan,
                'drug_exposure_start_datetime': start_date if pd.notna(start_date) else pd.NaT,
                'drug_exposure_end_date': end_date.date() if pd.notna(end_date) else np.nan,
                'drug_exposure_end_datetime': end_date if pd.notna(end_date) else pd.NaT,
                'quantity': row.get('EXDOSE') if 'EXDOSE' in row else np.nan,
                'dose_unit_source_value': row.get('EXDOSU') if 'EXDOSU' in row else None,
                'route_source_value': row.get('EXROUTE') if 'EXROUTE' in row else None,
                'drug_source_value': row.get('EXTRT'), # The specific study drug
                'drug_source_domain': 'EX' # Custom traceability flag
            })
            drug_id_counter += 1
            
    except FileNotFoundError:
        print(f"⚠️ Warning: File '{ex_path}' not found. Skipping EX domain.")

    # ---------------------------------------------------------
    # 2. PROCESS CONCOMITANT MEDICATIONS (CM)
    # ---------------------------------------------------------
    print(f"💊 Reading CDISC Concomitant Medications from: {cm_path}")
    try:
        df_cm = pd.read_sas(cm_path, format="sas7bdat", encoding="utf-8")
        
        for _, row in df_cm.iterrows():
            start_date = pd.to_datetime(row.get('CMSTDTC'), errors='coerce')
            end_date = pd.to_datetime(row.get('CMENDTC'), errors='coerce')
            
            drug_records.append({
                'drug_exposure_id': drug_id_counter,
                'person_id': generate_person_id(row.get('USUBJID')),
                'drug_concept_id': 0, # Pending AI Mapping to RxNorm
                'drug_type_concept_id': 32817, # OMOP standard for "EHR"
                'drug_exposure_start_date': start_date.date() if pd.notna(start_date) else np.nan,
                'drug_exposure_start_datetime': start_date if pd.notna(start_date) else pd.NaT,
                'drug_exposure_end_date': end_date.date() if pd.notna(end_date) else np.nan,
                'drug_exposure_end_datetime': end_date if pd.notna(end_date) else pd.NaT,
                'quantity': row.get('CMDOSE') if 'CMDOSE' in row else np.nan,
                'dose_unit_source_value': row.get('CMDOSU') if 'CMDOSU' in row else None, 
                'route_source_value': row.get('CMROUTE') if 'CMROUTE' in row else None,
                'drug_source_value': row.get('CMTRT'), # e.g. Paracetamol, Ibuprofen
                'drug_source_domain': 'CM' # Custom traceability flag
            })
            drug_id_counter += 1

    except FileNotFoundError:
        print(f"⚠️ Warning: File '{cm_path}' not found. Skipping CM domain.")

    # ---------------------------------------------------------
    # 3. BUILD AND EXPORT
    # ---------------------------------------------------------
    if not drug_records:
        print("❌ Error: No drug records found to process.")
        return

    print("\nMerging domains and building OMOP DRUG_EXPOSURE table...")
    df_drug = pd.DataFrame(drug_records)

    # Clean integers
    integer_cols = ['drug_exposure_id', 'person_id', 'drug_concept_id', 'drug_type_concept_id']
    for col in integer_cols:
        df_drug[col] = df_drug[col].astype('Int64')

    print(f"✅ DRUG_EXPOSURE table generated successfully with {len(df_drug)} records!")
    print(df_drug[['drug_exposure_id', 'drug_source_domain', 'drug_source_value', 'drug_exposure_start_date']].head(8))

    df_drug.to_csv(output_path, index=False)
    print(f"File saved to: {output_path}")

if __name__ == "__main__":
    EX_FILE = "data/raw/ex.sas7bdat"
    CM_FILE = "data/raw/cm.sas7bdat"
    OUTPUT_FILE = "data/processed/DRUG_EXPOSURE.csv"
    
    run_drug_etl(EX_FILE, CM_FILE, OUTPUT_FILE)