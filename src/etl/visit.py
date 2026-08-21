import pandas as pd
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))
from src.omop.type_concepts import type_concept_id_for
from src.utils.helpers import generate_person_id, parse_cdisc_date


def run_visit_etl(sv_path=None, output_path=None):
    """Transform actual SDTM SV records into OMOP VISIT_OCCURRENCE."""
    print("🏥 Extracting OMOP VISIT_OCCURRENCE from SDTM SV...")
    sv_path = Path(sv_path or PROJECT_ROOT / "data" / "raw" / "sv.sas7bdat")
    output_path = Path(
        output_path or PROJECT_ROOT / "data" / "processed" / "VISIT_OCCURRENCE.csv"
    )
    df_visits = pd.read_sas(sv_path, encoding="utf-8")
    required = {"USUBJID", "VISITNUM", "VISIT", "SVSTDTC", "SVENDTC"}
    missing = sorted(required.difference(df_visits.columns))
    if missing:
        raise ValueError("SV contract violation. Missing columns: " + ", ".join(missing))

    df_visits = df_visits.copy()
    df_visits["person_id"] = df_visits["USUBJID"].apply(generate_person_id)
    df_visits["source_visit_num"] = pd.to_numeric(df_visits["VISITNUM"], errors="coerce")
    df_visits["start_date"] = df_visits["SVSTDTC"].apply(parse_cdisc_date)
    df_visits["end_date"] = df_visits["SVENDTC"].apply(parse_cdisc_date)
    invalid = int(
        df_visits[["person_id", "source_visit_num", "VISIT", "start_date", "end_date"]]
        .isna().any(axis=1).sum()
    )
    reversed_dates = int((df_visits["end_date"] < df_visits["start_date"]).sum())
    duplicates = int(df_visits.duplicated(["person_id", "source_visit_num"]).sum())
    if invalid or reversed_dates or duplicates:
        raise ValueError(
            "SV contract violation. "
            f"Invalid required values: {invalid}; reversed visits: {reversed_dates}; "
            f"duplicate subject/visit numbers: {duplicates}."
        )

    df_visits = df_visits.sort_values(["person_id", "start_date", "source_visit_num"]).reset_index(drop=True)
    df_visits['visit_occurrence_id'] = range(1, len(df_visits) + 1)
    df_visits['visit_concept_id'] = 9202
    df_visits['visit_start_date'] = df_visits['start_date'].dt.strftime('%Y-%m-%d')
    df_visits['visit_end_date'] = df_visits['end_date'].dt.strftime('%Y-%m-%d')
    df_visits['visit_type_concept_id'] = type_concept_id_for('visit_occurrence', 'SV')
    df_visits['visit_source_value'] = df_visits['VISIT'].astype(str).str.strip()
    
    # Reorder columns
    final_cols = ['visit_occurrence_id', 'person_id', 'visit_concept_id', 'visit_start_date', 'visit_end_date', 'visit_type_concept_id', 'visit_source_value', 'source_visit_num']
    df_visits = df_visits[final_cols]
    
    # Ensure integers are clean
    df_visits['visit_occurrence_id'] = df_visits['visit_occurrence_id'].astype('Int64')
    df_visits['person_id'] = df_visits['person_id'].astype('Int64')
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df_visits.to_csv(output_path, index=False)
    
    print(f"✅ VISIT_OCCURRENCE generated with {len(df_visits)} actual visits!")
    print(df_visits[['visit_occurrence_id', 'person_id', 'visit_start_date']].head())

if __name__ == "__main__":
    run_visit_etl()
