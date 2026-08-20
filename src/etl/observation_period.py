import pandas as pd
import numpy as np
import os
import sys
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))
from src.utils.helpers import generate_person_id, parse_cdisc_date

def run_observation_period_etl():
    print("⏳ Calculating OBSERVATION_PERIOD...")
    
    dm_path = os.path.join(PROJECT_ROOT, "data", "raw", "dm.sas7bdat")
    try:
        df_dm = pd.read_sas(dm_path, encoding='utf-8')
    except Exception as e:
        print(f"❌ Error reading DM file: {e}")
        return

    df_dm['person_id'] = df_dm['USUBJID'].apply(generate_person_id)
    df_dm = df_dm.dropna(subset=['person_id'])

    # 1. SAFE EXTRACTION: Use .get() so it doesn't crash if columns are missing
    df_dm['start_date'] = pd.to_datetime(df_dm.get('RFSTDTC'), errors='coerce')
    df_dm['end_date'] = pd.to_datetime(df_dm.get('RFENDTC'), errors='coerce')
    
    # 2. FALLBACK LOGIC: If dates are missing, use active clinical events
    # CRITICAL: We explicitly EXCLUDE Medical History (MH) to avoid 30-year biases!
    raw_files = {
        'ae': ('AESTDTC', 'AEENDTC'),
        'ex': ('EXSTDTC', 'EXENDTC'),
        'lb': ('LBDTC', 'LBDTC'),
        'vs': ('VSDTC', 'VSDTC'),
        'eg': ('EGDTC', 'EGDTC')
    }
    
    event_dates = []
    for domain, (start_col, end_col) in raw_files.items():
        path = os.path.join(PROJECT_ROOT, "data", "raw", f"{domain}.sas7bdat")
        if os.path.exists(path):
            df = pd.read_sas(path, encoding='utf-8')
            df['person_id'] = df['USUBJID'].apply(generate_person_id)
            
            if start_col in df.columns:
                event_dates.append(df[['person_id', start_col]].rename(columns={start_col: 'date'}))
            if end_col in df.columns:
                event_dates.append(df[['person_id', end_col]].rename(columns={end_col: 'date'}))
                
    if event_dates:
        df_events = pd.concat(event_dates, ignore_index=True)
        df_events['date'] = df_events['date'].apply(parse_cdisc_date)
        df_events = df_events.dropna(subset=['date'])
        
        # Get min and max active date per person
        agg_dates = df_events.groupby('person_id')['date'].agg(['min', 'max']).reset_index()
        
        # Fill missing dates in DM
        df_dm = df_dm.merge(agg_dates, on='person_id', how='left')
        df_dm['start_date'] = df_dm['start_date'].fillna(df_dm['min'])
        df_dm['end_date'] = df_dm['end_date'].fillna(df_dm['max']).fillna(df_dm['start_date'])

    # Drop rows where we absolutely cannot determine a start date
    df_dm = df_dm.dropna(subset=['start_date'])

    # 3. Build OMOP OBSERVATION_PERIOD table
    df_obs = pd.DataFrame({
        'observation_period_id': range(1, len(df_dm) + 1),
        'person_id': df_dm['person_id'].astype('Int64'),
        'observation_period_start_date': df_dm['start_date'].dt.date,
        'observation_period_end_date': df_dm['end_date'].dt.date,
        'period_type_concept_id': 32817 # EHR clinical data concept
    })

    out_path = os.path.join(PROJECT_ROOT, "data", "processed", "OBSERVATION_PERIOD.csv")
    df_obs.to_csv(out_path, index=False)
    
    print(f"✅ OBSERVATION_PERIOD successfully generated with {len(df_obs)} records!")

if __name__ == "__main__":
    run_observation_period_etl()
