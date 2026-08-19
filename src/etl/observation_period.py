import pandas as pd
import os
import sys

# Add the src directory to the python path to import utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

def run_observation_period_etl():
    print("⏳ Calculating OBSERVATION_PERIOD from clinical events...")
    
    processed_dir = os.path.join("data", "processed")
    
    try:
        df_cond = pd.read_csv(os.path.join(processed_dir, "CONDITION_OCCURRENCE.csv"), usecols=['person_id', 'condition_start_date', 'condition_end_date'])
        df_drug = pd.read_csv(os.path.join(processed_dir, "DRUG_EXPOSURE.csv"), usecols=['person_id', 'drug_exposure_start_date', 'drug_exposure_end_date'])
        df_meas = pd.read_csv(os.path.join(processed_dir, "MEASUREMENT.csv"), usecols=['person_id', 'measurement_date'])
    except FileNotFoundError as e:
        print(f"❌ Error loading processed files for Observation Period: {e}")
        print("Make sure to run the clinical ETL scripts first.")
        return

    # 1. Gather all dates from all domains
    date_frames = []
    
    if not df_cond.empty:
        date_frames.append(df_cond[['person_id', 'condition_start_date']].rename(columns={'condition_start_date': 'date'}))
        date_frames.append(df_cond[['person_id', 'condition_end_date']].rename(columns={'condition_end_date': 'date'}))
        
    if not df_drug.empty:
        date_frames.append(df_drug[['person_id', 'drug_exposure_start_date']].rename(columns={'drug_exposure_start_date': 'date'}))
        date_frames.append(df_drug[['person_id', 'drug_exposure_end_date']].rename(columns={'drug_exposure_end_date': 'date'}))
        
    if not df_meas.empty:
        date_frames.append(df_meas[['person_id', 'measurement_date']].rename(columns={'measurement_date': 'date'}))
        
    # Combine everything and drop missing dates
    df_all_dates = pd.concat(date_frames).dropna()
    
    # Convert to strict datetime for accurate min/max calculations
    df_all_dates['date'] = pd.to_datetime(df_all_dates['date'], errors='coerce')
    df_all_dates = df_all_dates.dropna()
    
    # 2. Group by person to find absolute first and last clinical interaction
    print("🧠 Aggregating longitudinal timelines per patient...")
    obs_period = df_all_dates.groupby('person_id')['date'].agg(['min', 'max']).reset_index()
    
    # Rename columns to match OMOP standard
    obs_period.rename(columns={
        'min': 'observation_period_start_date',
        'max': 'observation_period_end_date'
    }, inplace=True)
    
    # 3. Add mandatory OMOP fields
    obs_period['observation_period_id'] = range(1, len(obs_period) + 1)
    obs_period['period_type_concept_id'] = 32817 # OMOP standard for "EHR"
    
    # Format dates back to clean strings (YYYY-MM-DD)
    obs_period['observation_period_start_date'] = obs_period['observation_period_start_date'].dt.strftime('%Y-%m-%d')
    obs_period['observation_period_end_date'] = obs_period['observation_period_end_date'].dt.strftime('%Y-%m-%d')
    
    # Reorder columns
    final_cols = ['observation_period_id', 'person_id', 'observation_period_start_date', 'observation_period_end_date', 'period_type_concept_id']
    obs_period = obs_period[final_cols]
    
    # Ensure integers are clean
    obs_period['observation_period_id'] = obs_period['observation_period_id'].astype('Int64')
    obs_period['person_id'] = obs_period['person_id'].astype('Int64')
    
    output_path = os.path.join(processed_dir, "OBSERVATION_PERIOD.csv")
    obs_period.to_csv(output_path, index=False)
    
    print(f"✅ OBSERVATION_PERIOD successfully generated with {len(obs_period)} records!")
    print(obs_period.head())

if __name__ == "__main__":
    run_observation_period_etl()