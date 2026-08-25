import os
import sys
import duckdb
import pandas as pd
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))
from src.utils.config import DB_PATH, PROCESSED_DIR
from src.utils.run_context import require_run_id
from src.mapping.review_store import get_vocabulary_version

def get_standard_concept(term, domain, con):
    """
    Tries to map a raw term to a Standard OMOP Concept using:
    1. Direct match to a Standard Concept.
    2. 'Maps to' relationship from a Non-Standard Concept.
    """
    term_lower = str(term).lower().strip()
    
    # Strategy 1: Direct Match to a Standard Concept
    query_direct = """
        SELECT concept_id, concept_name 
        FROM concept 
        WHERE LOWER(concept_name) = ? 
          AND domain_id = ? 
          AND standard_concept = 'S'
          AND (invalid_reason IS NULL OR invalid_reason = '')
          AND CURRENT_DATE BETWEEN valid_start_date AND valid_end_date
        ORDER BY concept_id
        LIMIT 2
    """
    direct_matches = con.execute(
        query_direct,
        (term_lower, domain),
    ).fetchall()
    if len(direct_matches) == 1:
        return (
            direct_matches[0][0],
            direct_matches[0][1],
            "deterministic_direct_match",
        )
    if len(direct_matches) > 1:
        return 0, None, "ambiguous_direct_match"
        
    # Strategy 2: Match to a Non-Standard Concept, then follow 'Maps to'
    query_maps_to = """
        SELECT DISTINCT c2.concept_id, c2.concept_name
        FROM concept c1
        JOIN concept_relationship cr ON c1.concept_id = cr.concept_id_1
        JOIN concept c2 ON cr.concept_id_2 = c2.concept_id
        WHERE LOWER(c1.concept_name) = ?
          AND cr.relationship_id = 'Maps to'
          AND (c1.invalid_reason IS NULL OR c1.invalid_reason = '')
          AND CURRENT_DATE BETWEEN c1.valid_start_date AND c1.valid_end_date
          AND (cr.invalid_reason IS NULL OR cr.invalid_reason = '')
          AND CURRENT_DATE BETWEEN cr.valid_start_date AND cr.valid_end_date
          AND c2.standard_concept = 'S'
          AND c2.domain_id = ?
          AND (c2.invalid_reason IS NULL OR c2.invalid_reason = '')
          AND CURRENT_DATE BETWEEN c2.valid_start_date AND c2.valid_end_date
        ORDER BY c2.concept_id
        LIMIT 2
    """
    maps_to_matches = con.execute(
        query_maps_to,
        (term_lower, domain),
    ).fetchall()
    if len(maps_to_matches) == 1:
        return (
            maps_to_matches[0][0],
            maps_to_matches[0][1],
            "deterministic_maps_to_relation",
        )
    if len(maps_to_matches) > 1:
        return 0, None, "ambiguous_maps_to_relation"
        
    return 0, None, None

def process_domain(
    df, source_col, concept_col, id_col, domain_name, target_table, con, run_id
):
    unmapped_mask = df[concept_col] == 0
    unique_terms = df[unmapped_mask][source_col].dropna().unique()
    
    if len(unique_terms) == 0:
        return df, 0
        
    mapping_dict = {}
    audit_records = []
    ambiguous_terms = []
    
    vocab_version = get_vocabulary_version(con)

    for term in unique_terms:
        concept_id, concept_name, method = get_standard_concept(term, domain_name, con)
        if method and method.startswith("ambiguous_"):
            ambiguous_terms.append(str(term))
        if concept_id != 0:
            mapping_dict[term] = concept_id
            
            # Find all rows that are getting this mapping for the Audit Trail
            affected_ids = df[(df[concept_col] == 0) & (df[source_col] == term)][id_col].tolist()
            for record_id in affected_ids:
                audit_records.append((
                    target_table, int(record_id), term, term, int(concept_id), 
                    method, 1.0, 'OHDSI_Vocabulary', vocab_version,
                    'System_Auto_Approved', run_id
                ))

    # Apply mappings
    # Apply mappings safely by unifying types
    if mapping_dict:
        # 1. Force the column to numeric FIRST to avoid PyArrow string conflicts
        df[concept_col] = pd.to_numeric(df[concept_col], errors='coerce').fillna(0).astype('Int64')
        
        # 2. Re-calculate mask to ensure safe boolean indexing
        mask = (df[concept_col] == 0) & (df[source_col].isin(mapping_dict.keys()))
        
        # 3. Inject the mapped integers safely
        df.loc[mask, concept_col] = df.loc[mask, source_col].map(mapping_dict).astype('Int64')
        
        # Write to Provenance Table
        if audit_records:
            con.executemany("""
                INSERT INTO mapping_provenance (
                    target_table, target_id, source_value, normalized_value,
                    assigned_concept_id, mapping_method, score, model_name,
                    vocabulary_version, reviewed_by, run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
            """, audit_records)
            
    print(f"[{domain_name}] Successfully mapped {len(mapping_dict)} out of {len(unique_terms)} unique terms deterministically.")
    if ambiguous_terms:
        print(
            f"[{domain_name}] Left {len(ambiguous_terms)} ambiguous exact/Maps To "
            "term(s) for guarded proposal and human review: "
            + ", ".join(sorted(ambiguous_terms))
        )
    return df, len(mapping_dict)

def run_deterministic_mapping():
    print("⚙️ STARTING DETERMINISTIC MAPPING (OHDSI 'MAPS TO' RELATIONSHIPS)")
    print("-" * 50)
    
    run_id = require_run_id()
    cond_path = os.path.join(PROCESSED_DIR, "CONDITION_OCCURRENCE.csv")
    drug_path = os.path.join(PROCESSED_DIR, "DRUG_EXPOSURE.csv")
    meas_path = os.path.join(PROCESSED_DIR, "MEASUREMENT.csv")
    
    with duckdb.connect(DB_PATH) as con:
        # 1. Conditions
        print("🔍 Mapping CONDITIONS...")
        if os.path.exists(cond_path):
            df_cond = pd.read_csv(cond_path)
            df_cond, mapped_c = process_domain(
                df_cond, 'condition_source_value', 'condition_concept_id', 'condition_occurrence_id',
                'Condition', 'condition_occurrence', con, run_id
            )
            if mapped_c > 0:
                df_cond.to_csv(cond_path, index=False)
                
        # 2. Drugs
        print("🔍 Mapping DRUGS...")
        if os.path.exists(drug_path):
            df_drug = pd.read_csv(drug_path)
            df_drug, mapped_d = process_domain(
                df_drug, 'drug_mapping_value', 'drug_concept_id', 'drug_exposure_id',
                'Drug', 'drug_exposure', con, run_id
            )
            if mapped_d > 0:
                df_drug.to_csv(drug_path, index=False)

        # 3. Measurements
        print("🔍 Mapping MEASUREMENTS...")
        if os.path.exists(meas_path):
            df_meas = pd.read_csv(meas_path)
            df_meas, mapped_m = process_domain(
                df_meas, 'measurement_source_value', 'measurement_concept_id', 'measurement_id',
                'Measurement', 'measurement', con, run_id
            )
            if mapped_m > 0:
                df_meas.to_csv(meas_path, index=False)

    print("-" * 50)
    print("✅ Deterministic mapping & Audit logging complete! Processed files updated.")

if __name__ == "__main__":
    run_deterministic_mapping()
