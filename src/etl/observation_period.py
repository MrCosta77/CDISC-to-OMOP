import pandas as pd
import sys
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))
from src.utils.helpers import generate_person_id, parse_cdisc_date
from src.omop.type_concepts import type_concept_id_for

def run_observation_period_etl(dm_path=None, output_path=None):
    """Build one observation period per DM subject from RFSTDTC/RFENDTC."""
    print("⏳ Calculating OBSERVATION_PERIOD from the DM reference period...")
    dm_path = Path(dm_path or PROJECT_ROOT / "data" / "raw" / "dm.sas7bdat")
    output_path = Path(
        output_path
        or PROJECT_ROOT / "data" / "processed" / "OBSERVATION_PERIOD.csv"
    )
    df_dm = pd.read_sas(dm_path, encoding="utf-8")

    required = {"USUBJID", "RFSTDTC", "RFENDTC"}
    missing = sorted(required.difference(df_dm.columns))
    if missing:
        raise ValueError(
            "DM observation-period contract violation. Missing columns: "
            + ", ".join(missing)
        )

    df_dm['person_id'] = df_dm['USUBJID'].apply(generate_person_id)
    df_dm["start_date"] = df_dm["RFSTDTC"].apply(parse_cdisc_date)
    df_dm["end_date"] = df_dm["RFENDTC"].apply(parse_cdisc_date)
    invalid_ids = int(df_dm["person_id"].isna().sum())
    invalid_starts = int(df_dm["start_date"].isna().sum())
    invalid_ends = int(df_dm["end_date"].isna().sum())
    reversed_periods = int((df_dm["end_date"] < df_dm["start_date"]).sum())
    duplicate_people = int(df_dm["person_id"].duplicated().sum())
    if any((invalid_ids, invalid_starts, invalid_ends, reversed_periods, duplicate_people)):
        raise ValueError(
            "DM observation-period contract violation. "
            f"Missing subject IDs: {invalid_ids}; invalid starts: {invalid_starts}; "
            f"invalid ends: {invalid_ends}; reversed periods: {reversed_periods}; "
            f"duplicate subjects: {duplicate_people}."
        )

    # 3. Build OMOP OBSERVATION_PERIOD table
    df_obs = pd.DataFrame({
        'observation_period_id': range(1, len(df_dm) + 1),
        'person_id': df_dm['person_id'].astype('Int64'),
        'observation_period_start_date': df_dm['start_date'].dt.date,
        'observation_period_end_date': df_dm['end_date'].dt.date,
        'period_type_concept_id': type_concept_id_for(
            'observation_period', 'DERIVED'
        )
    })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df_obs.to_csv(output_path, index=False)
    
    print(f"✅ OBSERVATION_PERIOD successfully generated with {len(df_obs)} records!")

if __name__ == "__main__":
    run_observation_period_etl()
