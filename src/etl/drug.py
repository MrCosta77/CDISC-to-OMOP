import pandas as pd
import numpy as np
import sys
import os

# Add the src directory to the python path to import utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.utils.helpers import generate_person_id
from src.omop.type_concepts import type_concept_id_for


def _mapping_value(coded_value, verbatim_value):
    if pd.notna(coded_value) and str(coded_value).strip():
        return str(coded_value).strip()
    return verbatim_value


def _reference_end_dates(dm_path):
    """Return each subject's administrative observation boundary from DM."""
    dm = pd.read_sas(dm_path, format="sas7bdat", encoding="utf-8")
    required = {"USUBJID", "RFENDTC"}
    missing = sorted(required.difference(dm.columns))
    if missing:
        raise ValueError(
            "DM drug-censoring contract violation. Missing columns: "
            + ", ".join(missing)
        )
    if dm["USUBJID"].duplicated().any():
        raise ValueError("DM drug-censoring contract violation: duplicate USUBJID.")
    ends = pd.to_datetime(dm["RFENDTC"], errors="coerce")
    if ends.isna().any():
        raise ValueError(
            "DM drug-censoring contract violation: invalid RFENDTC values."
        )
    return dict(zip(dm["USUBJID"].astype(str), ends))


def _end_date_fields(source_end, published_end, derivation):
    return {
        "drug_exposure_end_date": (
            published_end.date() if pd.notna(published_end) else np.nan
        ),
        "drug_exposure_end_datetime": (
            published_end if pd.notna(published_end) else pd.NaT
        ),
        # OMOP VERBATIM_END_DATE is populated only when an end date was
        # explicitly present in the source record.
        "verbatim_end_date": (
            source_end.date() if pd.notna(source_end) else np.nan
        ),
        "source_end_date": source_end.date() if pd.notna(source_end) else None,
        "published_end_date": (
            published_end.date() if pd.notna(published_end) else None
        ),
        "end_date_derivation": derivation,
    }

def run_drug_etl(ex_path, cm_path, output_path, dm_path=None):
    """
    Extracts Exposure (EX) and Concomitant Medications (CM) data 
    and transforms them into a unified OMOP DRUG_EXPOSURE table.
    """
    dm_path = dm_path or os.path.join(os.path.dirname(ex_path), "dm.sas7bdat")
    reference_ends = _reference_end_dates(dm_path)
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
            published_end_date = end_date if pd.notna(end_date) else start_date
            end_derivation = (
                "SOURCE_RECORDED"
                if pd.notna(end_date)
                else "OHDSI_ADMINISTRATION_SAME_DAY"
            )
            
            drug_records.append({
                'drug_exposure_id': drug_id_counter,
                'person_id': generate_person_id(row.get('USUBJID')),
                'drug_concept_id': 0, # Pending AI Mapping to RxNorm
                'drug_type_concept_id': type_concept_id_for(
                    'drug_exposure', 'EX'
                ),
                'drug_exposure_start_date': start_date.date() if pd.notna(start_date) else np.nan,
                'drug_exposure_start_datetime': start_date if pd.notna(start_date) else pd.NaT,
                **_end_date_fields(
                    end_date, published_end_date, end_derivation
                ),
                'quantity': row.get('EXDOSE') if 'EXDOSE' in row else np.nan,
                'dose_unit_source_value': row.get('EXDOSU') if 'EXDOSU' in row else None,
                'route_source_value': row.get('EXROUTE') if 'EXROUTE' in row else None,
                'drug_source_value': row.get('EXTRT'), # The specific study drug
                'drug_mapping_value': row.get('EXTRT'),
                'drug_source_concept_id': 0,
                'drug_source_domain': 'EX', # Custom traceability flag
                'source_subject_id': row.get('USUBJID'),
                'source_record_key': f"EXSEQ={int(row.get('EXSEQ'))}",
                'source_record_value': row.get('EXTRT'),
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
            ongoing = str(row.get("CMENRTPT") or "").strip().upper() == "ONGOING"
            if pd.notna(end_date):
                published_end_date = end_date
                end_derivation = "SOURCE_RECORDED"
            elif ongoing:
                subject = str(row.get("USUBJID"))
                published_end_date = reference_ends.get(subject)
                if pd.isna(published_end_date):
                    raise ValueError(
                        f"CM ongoing record has no DM RFENDTC boundary: {subject}."
                    )
                end_derivation = "ADMINISTRATIVE_CENSORING_RFENDTC"
            else:
                raise ValueError(
                    "CM record has no CMENDTC and is not explicitly ONGOING: "
                    f"{row.get('USUBJID')} CMSEQ={row.get('CMSEQ')}."
                )
            
            drug_records.append({
                'drug_exposure_id': drug_id_counter,
                'person_id': generate_person_id(row.get('USUBJID')),
                'drug_concept_id': 0, # Pending AI Mapping to RxNorm
                'drug_type_concept_id': type_concept_id_for(
                    'drug_exposure', 'CM'
                ),
                'drug_exposure_start_date': start_date.date() if pd.notna(start_date) else np.nan,
                'drug_exposure_start_datetime': start_date if pd.notna(start_date) else pd.NaT,
                **_end_date_fields(
                    end_date, published_end_date, end_derivation
                ),
                'quantity': row.get('CMDOSE') if 'CMDOSE' in row else np.nan,
                'dose_unit_source_value': row.get('CMDOSU') if 'CMDOSU' in row else None, 
                'route_source_value': row.get('CMROUTE') if 'CMROUTE' in row else None,
                'drug_source_value': row.get('CMTRT'), # verbatim source term
                'drug_mapping_value': _mapping_value(
                    row.get('CMDECOD'), row.get('CMTRT')
                ),
                'drug_source_concept_id': 0,
                'drug_source_domain': 'CM', # Custom traceability flag
                'source_subject_id': row.get('USUBJID'),
                'source_record_key': f"CMSEQ={int(row.get('CMSEQ'))}",
                'source_record_value': row.get('CMTRT'),
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
    integer_cols = [
        'drug_exposure_id', 'person_id', 'drug_concept_id',
        'drug_type_concept_id', 'drug_source_concept_id'
    ]
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
