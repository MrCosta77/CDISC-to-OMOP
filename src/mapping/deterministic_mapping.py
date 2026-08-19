import os
import sys
import duckdb
import pandas as pd
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))
from src.utils.config import DB_PATH

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
        LIMIT 1
    """
    res = con.execute(query_direct, (term_lower, domain)).fetchone()
    if res:
        return res[0], res[1], "deterministic_direct_match"
        
    # Strategy 2: Match to a Non-Standard Concept, then follow 'Maps to'
    query_maps_to = """
        SELECT c2.concept_id, c2.concept_name
        FROM concept c1
        JOIN concept_relationship cr ON c1.concept_id = cr.concept_id_1
        JOIN concept c2 ON cr.concept_id_2 = c2.concept_id
        WHERE LOWER(c1.concept_name) = ?
          AND cr.relationship_id = 'Maps to'
          AND c2.standard_concept = 'S'
          AND c2.domain_id = ?
        LIMIT 1
    """
    res = con.execute(query_maps_to, (term_lower, domain)).fetchone()
    if res:
        return res[0], res[1], "deterministic_maps_to_relation"
        
    return 0, None, None

def process_domain(df, source_col, concept_col, id_col, domain_name, target_table, con):
    unmapped_mask = df[concept_col] == 0
    unique_terms = df[unmapped_mask][source_col].dropna().unique()
    
    if len(unique_terms) == 0:
        return df, 0
        
    mapping_dict = {}
    audit_records = []
    
    try:
        vocab_version = con.execute("SELECT vocabulary_version FROM vocabulary WHERE vocabulary_id = 'None'").fetchone()[0]
    except:
        vocab_version = 'Athena_Standard'

    for term in unique_terms:
        concept_id, concept_name, method = get_standard_concept(term, domain_name, con)
        if concept_id != 0:
            mapping_dict[term] = concept_id
            
            # Find all rows that are getting this mapping for the Audit Trail
            affected_ids = df[(df[concept_col] == 0) & (df[source_col] == term)][id_col].tolist()
            for record_id in affected_ids:
                audit_records.append((
                    target_table, int(record_id), term, term, int(concept_id), 
                    method, 1.0, 'OHDSI_Vocabulary', vocab_version, 'System_Auto_Approved'
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
                    vocabulary_version, reviewed_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, audit_records)
            
    print(f"[{domain_name}] Successfully mapped {len(mapping_dict)} out of {len(unique_terms)} unique terms deterministically.")
    return df, len(mapping_dict)

def run_deterministic_mapping():
    print("⚙️ STARTING DETERMINISTIC MAPPING (OHDSI 'MAPS TO' RELATIONSHIPS)")
    print("-" * 50)
    
    cond_path = os.path.join(PROJECT_ROOT, "data", "processed", "CONDITION_OCCURRENCE.csv")
    drug_path = os.path.join(PROJECT_ROOT, "data", "processed", "DRUG_EXPOSURE.csv")
    meas_path = os.path.join(PROJECT_ROOT, "data", "processed", "MEASUREMENT.csv") 
    
    with duckdb.connect(DB_PATH) as con:
        # 1. Conditions
        print("🔍 Mapping CONDITIONS...")
        if os.path.exists(cond_path):
            df_cond = pd.read_csv(cond_path)
            df_cond, mapped_c = process_domain(
                df_cond, 'condition_source_value', 'condition_concept_id', 'condition_occurrence_id',
                'Condition', 'condition_occurrence', con
            )
            if mapped_c > 0:
                df_cond.to_csv(cond_path, index=False)
                
        # 2. Drugs
        print("🔍 Mapping DRUGS...")
        if os.path.exists(drug_path):
            df_drug = pd.read_csv(drug_path)
            df_drug, mapped_d = process_domain(
                df_drug, 'drug_source_value', 'drug_concept_id', 'drug_exposure_id',
                'Drug', 'drug_exposure', con
            )
            if mapped_d > 0:
                df_drug.to_csv(drug_path, index=False)

        # 3. Measurements
        print("🔍 Mapping MEASUREMENTS...")
        if os.path.exists(meas_path):
            df_meas = pd.read_csv(meas_path)
            df_meas, mapped_m = process_domain(
                df_meas, 'measurement_source_value', 'measurement_concept_id', 'measurement_id',
                'Measurement', 'measurement', con
            )
            if mapped_m > 0:
                df_meas.to_csv(meas_path, index=False)

    print("-" * 50)
    print("✅ Deterministic mapping & Audit logging complete! Processed files updated.")

if __name__ == "__main__":
    run_deterministic_mapping()