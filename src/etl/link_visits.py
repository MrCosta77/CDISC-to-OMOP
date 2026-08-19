import pandas as pd
import os
import sys

# Add the src directory to the python path to import utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

def run_visit_linking():
    print("🔗 Linking clinical events to their respective visits...")
    
    processed_dir = os.path.join("data", "processed")
    
    try:
        df_visit = pd.read_csv(os.path.join(processed_dir, "VISIT_OCCURRENCE.csv"))
        df_cond = pd.read_csv(os.path.join(processed_dir, "CONDITION_OCCURRENCE.csv"))
        df_drug = pd.read_csv(os.path.join(processed_dir, "DRUG_EXPOSURE.csv"))
        df_meas = pd.read_csv(os.path.join(processed_dir, "MEASUREMENT.csv"))
    except FileNotFoundError as e:
        print(f"❌ Error loading files for linking: {e}")
        print("Make sure to run the visit derivation script first.")
        return

    # 1. Create a lookup dictionary: (person_id, date) -> visit_occurrence_id
    print("🧠 Building mapping dictionary...")
    visit_mapping = df_visit.set_index(['person_id', 'visit_start_date'])['visit_occurrence_id'].to_dict()

    # 2. Link Conditions
    print("   - Updating CONDITION_OCCURRENCE...")
    df_cond['visit_occurrence_id'] = df_cond.set_index(['person_id', 'condition_start_date']).index.map(visit_mapping)
    df_cond['visit_occurrence_id'] = df_cond['visit_occurrence_id'].astype('Int64')
    df_cond.to_csv(os.path.join(processed_dir, "CONDITION_OCCURRENCE.csv"), index=False)

    # 3. Link Drugs
    print("   - Updating DRUG_EXPOSURE...")
    df_drug['visit_occurrence_id'] = df_drug.set_index(['person_id', 'drug_exposure_start_date']).index.map(visit_mapping)
    df_drug['visit_occurrence_id'] = df_drug['visit_occurrence_id'].astype('Int64')
    df_drug.to_csv(os.path.join(processed_dir, "DRUG_EXPOSURE.csv"), index=False)

    # 4. Link Measurements
    print("   - Updating MEASUREMENT...")
    df_meas['visit_occurrence_id'] = df_meas.set_index(['person_id', 'measurement_date']).index.map(visit_mapping)
    df_meas['visit_occurrence_id'] = df_meas['visit_occurrence_id'].astype('Int64')
    df_meas.to_csv(os.path.join(processed_dir, "MEASUREMENT.csv"), index=False)

    print("✅ All clinical domains successfully linked to visits!")

if __name__ == "__main__":
    run_visit_linking()