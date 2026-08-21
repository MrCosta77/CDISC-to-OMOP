import pandas as pd
import numpy as np
import sys
import os

# Add the src directory to the python path to import utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.utils.helpers import generate_person_id, parse_cdisc_date

def run_etl_condition(ae_path, mh_path, output_path):
    """
    Extracts Adverse Events (AE) and Medical History (MH) data 
    and transforms them into a unified OMOP CONDITION_OCCURRENCE table.
    """
    condition_records = []
    condition_id_counter = 1

    # ---------------------------------------------------------
    # 1. PROCESS ADVERSE EVENTS (AE)
    # ---------------------------------------------------------
    print(f"🩺 Reading CDISC Adverse Events from: {ae_path}")
    try:
        df_ae = pd.read_sas(ae_path, format="sas7bdat", encoding="utf-8")
        
        for _, row in df_ae.iterrows():
            start_date = parse_cdisc_date(row.get('AESTDTC'))
            end_date = parse_cdisc_date(row.get('AEENDTC'))
            
            # Prioritize AETERM, fallback to AEDECOD if empty
            source_value = row.get('AETERM')
            if pd.isna(source_value) or str(source_value).strip() == '':
                source_value = row.get('AEDECOD')

            condition_records.append({
                'condition_occurrence_id': condition_id_counter,
                'person_id': generate_person_id(row.get('USUBJID')),
                'condition_concept_id': 0, # Pending AI Mapping
                'condition_type_concept_id': 32020, # OMOP standard for "EHR encounter diagnosis"
                'condition_start_date': start_date.date() if pd.notna(start_date) else np.nan,
                'condition_start_datetime': start_date if pd.notna(start_date) else pd.NaT,
                'condition_end_date': end_date.date() if pd.notna(end_date) else np.nan,
                'condition_end_datetime': end_date if pd.notna(end_date) else pd.NaT,
                'condition_source_value': source_value,
                'condition_status_source_value': row.get('AEOUT') # Specific AE outcome (e.g., RECOVERED)
            })
            condition_id_counter += 1
            
    except FileNotFoundError:
        print(f"⚠️ Warning: File '{ae_path}' not found. Skipping AE domain.")

    # ---------------------------------------------------------
    # 2. PROCESS MEDICAL HISTORY (MH)
    # ---------------------------------------------------------
    print(f"🩺 Reading CDISC Medical History from: {mh_path}")
    try:
        df_mh = pd.read_sas(mh_path, format="sas7bdat", encoding="utf-8")

        required_columns = {'USUBJID', 'MHTERM', 'MHSTDTC'}
        missing_columns = sorted(required_columns.difference(df_mh.columns))
        if missing_columns:
            raise ValueError(
                "MH data contract violation. Missing required columns: "
                + ", ".join(missing_columns)
            )

        df_mh = df_mh.copy()
        df_mh['_parsed_date'] = df_mh['MHSTDTC'].apply(parse_cdisc_date)
        invalid_dates = int(df_mh['_parsed_date'].isna().sum())
        missing_terms = int(df_mh['MHTERM'].isna().sum())
        if invalid_dates or missing_terms:
            raise ValueError(
                "MH data contract violation. "
                f"Unparseable dates: {invalid_dates}; missing terms: {missing_terms}."
            )
        
        for _, row in df_mh.iterrows():
            # In SDTM, MH diagnosis dates are usually captured in MHSTDTC
            start_date = row['_parsed_date']
            
            condition_records.append({
                'condition_occurrence_id': condition_id_counter,
                'person_id': generate_person_id(row.get('USUBJID')),
                'condition_concept_id': 0, # Pending AI Mapping
                'condition_type_concept_id': 32817, # OMOP standard for "EHR" (General medical history)
                'condition_start_date': start_date.date() if pd.notna(start_date) else np.nan,
                'condition_start_datetime': start_date if pd.notna(start_date) else pd.NaT,
                # Chronic Medical History usually lacks an explicit end date in base SDTM
                'condition_end_date': np.nan, 
                'condition_end_datetime': pd.NaT,
                'condition_source_value': row.get('MHTERM'),
                'condition_status_source_value': 'Medical History' # Traceability flag
            })
            condition_id_counter += 1

    except FileNotFoundError:
        print(f"⚠️ Warning: File '{mh_path}' not found. Skipping MH domain.")

    # ---------------------------------------------------------
    # 3. BUILD AND EXPORT
    # ---------------------------------------------------------
    if not condition_records:
        print("❌ Error: No condition records found to process.")
        return

    print("\nMerging domains and building OMOP CONDITION_OCCURRENCE table...")
    df_condition = pd.DataFrame(condition_records)

    # Clean integers to avoid decimals on empty values
    integer_cols = ['condition_occurrence_id', 'person_id', 'condition_concept_id', 'condition_type_concept_id']
    for col in integer_cols:
        df_condition[col] = df_condition[col].astype('Int64')

    print(f"✅ CONDITION_OCCURRENCE table generated successfully with {len(df_condition)} records!")
    print(df_condition[['condition_occurrence_id', 'person_id', 'condition_source_value', 'condition_status_source_value']].head(8))

    df_condition.to_csv(output_path, index=False)
    print(f"File saved to: {output_path}")

if __name__ == "__main__":
    AE_FILE = "data/raw/ae.sas7bdat"
    MH_FILE = "data/raw/mh.sas7bdat"
    OUTPUT_FILE = "data/processed/CONDITION_OCCURRENCE.csv"
    
    run_etl_condition(AE_FILE, MH_FILE, OUTPUT_FILE)
