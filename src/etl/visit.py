import pandas as pd
import os
import sys

# Add the src directory to the python path to import utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.omop.type_concepts import type_concept_id_for

def run_visit_etl():
    print("🏥 Deriving OMOP VISIT_OCCURRENCE from clinical events...")
    
    processed_dir = os.path.join("data", "processed")
    
    try:
        df_cond = pd.read_csv(os.path.join(processed_dir, "CONDITION_OCCURRENCE.csv"), usecols=['person_id', 'condition_start_date'])
        df_drug = pd.read_csv(os.path.join(processed_dir, "DRUG_EXPOSURE.csv"), usecols=['person_id', 'drug_exposure_start_date'])
        df_meas = pd.read_csv(os.path.join(processed_dir, "MEASUREMENT.csv"), usecols=['person_id', 'measurement_date'])
    except FileNotFoundError as e:
        print(f"❌ Error loading processed files for Visits: {e}")
        print("Make sure to run the clinical ETL scripts first.")
        return

    # 1. Gather all start dates from all domains
    date_frames = []
    
    if not df_cond.empty:
        date_frames.append(df_cond.rename(columns={'condition_start_date': 'date'}))
    if not df_drug.empty:
        date_frames.append(df_drug.rename(columns={'drug_exposure_start_date': 'date'}))
    if not df_meas.empty:
        date_frames.append(df_meas.rename(columns={'measurement_date': 'date'}))
        
    df_all_dates = pd.concat(date_frames).dropna()
    
    # Convert to strict datetime
    df_all_dates['date'] = pd.to_datetime(df_all_dates['date'], errors='coerce')
    df_all_dates = df_all_dates.dropna()
    
    # 2. Extract unique (person_id, date) combinations to represent clinical visits
    print("🧠 Extracting unique clinical interaction dates per patient...")
    df_visits = df_all_dates.drop_duplicates().sort_values(by=['person_id', 'date']).reset_index(drop=True)
    
    # 3. Build the standard OMOP VISIT_OCCURRENCE table
    df_visits['visit_occurrence_id'] = range(1, len(df_visits) + 1)
    df_visits['visit_concept_id'] = 9202 # OMOP standard for "Outpatient Visit"
    df_visits['visit_start_date'] = df_visits['date'].dt.strftime('%Y-%m-%d')
    df_visits['visit_end_date'] = df_visits['date'].dt.strftime('%Y-%m-%d')
    df_visits['visit_type_concept_id'] = type_concept_id_for(
        'visit_occurrence', 'DERIVED'
    )
    df_visits['visit_source_value'] = 'Derived from clinical event'
    
    # Reorder columns
    final_cols = ['visit_occurrence_id', 'person_id', 'visit_concept_id', 'visit_start_date', 'visit_end_date', 'visit_type_concept_id', 'visit_source_value']
    df_visits = df_visits[final_cols]
    
    # Ensure integers are clean
    df_visits['visit_occurrence_id'] = df_visits['visit_occurrence_id'].astype('Int64')
    df_visits['person_id'] = df_visits['person_id'].astype('Int64')
    
    output_path = os.path.join(processed_dir, "VISIT_OCCURRENCE.csv")
    df_visits.to_csv(output_path, index=False)
    
    print(f"✅ VISIT_OCCURRENCE successfully derived with {len(df_visits)} unique visits!")
    print(df_visits[['visit_occurrence_id', 'person_id', 'visit_start_date']].head())

if __name__ == "__main__":
    run_visit_etl()
