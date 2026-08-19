import pandas as pd
import duckdb
import os
import sys
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))
from src.utils.config import DB_PATH

def map_domain(df, source_col, concept_col, domain_id, con):
    """Maps source values to standard OMOP concept IDs using exact string matching."""
    
    # Get unique unmapped terms (where concept_id is 0)
    unmapped_terms = df[df[concept_col] == 0][source_col].dropna().unique()
    
    mapping_dict = {}
    for term in unmapped_terms:
        # Query DuckDB for an exact case-insensitive match for Standard Concepts ('S')
        # We explicitly cast concept_id to INTEGER (::INTEGER) because the vocabulary was loaded as VARCHAR
        query = f"""
            SELECT concept_id::INTEGER
            FROM concept
            WHERE LOWER(concept_name) = LOWER(?)
              AND standard_concept = 'S'
              AND domain_id = '{domain_id}'
            ORDER BY vocabulary_id DESC 
            LIMIT 1
        """
        result = con.execute(query, (term,)).fetchone()
        
        if result:
            mapping_dict[term] = int(result[0])
            
    # Apply the successful mappings to the dataframe
    if mapping_dict:
        # Create a mask for rows that are currently 0 AND whose source value found a match
        mask = (df[concept_col] == 0) & (df[source_col].isin(mapping_dict.keys()))
        
        # Apply the mapping and explicitly cast to pandas Int64 to maintain clean datatypes
        df.loc[mask, concept_col] = df.loc[mask, source_col].map(mapping_dict).astype('Int64')
        
    print(f"[{domain_id}] Successfully mapped {len(mapping_dict)} out of {len(unmapped_terms)} unique terms deterministically.")
    return df

def run_deterministic_mapping():
    print("⚙️ STARTING DETERMINISTIC MAPPING (EXACT STRING MATCH)")
    print("-" * 50)
    
    condition_path = os.path.join(PROJECT_ROOT, "data", "processed", "CONDITION_OCCURRENCE.csv")
    drug_path = os.path.join(PROJECT_ROOT, "data", "processed", "DRUG_EXPOSURE.csv")
    
    try:
        df_cond = pd.read_csv(condition_path)
        df_drug = pd.read_csv(drug_path)
    except FileNotFoundError as e:
        print(f"❌ Error loading processed files: {e}")
        return

    with duckdb.connect(DB_PATH) as con:
        print("🔍 Mapping CONDITIONS...")
        df_cond = map_domain(df_cond, 'condition_source_value', 'condition_concept_id', 'Condition', con)
        
        print("🔍 Mapping DRUGS...")
        df_drug = map_domain(df_drug, 'drug_source_value', 'drug_concept_id', 'Drug', con)
        
    # Save updated DataFrames back to CSV, preserving Int64 types to avoid decimals
    for col in ['condition_concept_id', 'person_id', 'condition_occurrence_id', 'condition_type_concept_id']:
        if col in df_cond.columns:
            df_cond[col] = df_cond[col].astype('Int64')
            
    for col in ['drug_concept_id', 'person_id', 'drug_exposure_id', 'drug_type_concept_id']:
        if col in df_drug.columns:
            df_drug[col] = df_drug[col].astype('Int64')

    df_cond.to_csv(condition_path, index=False)
    df_drug.to_csv(drug_path, index=False)
    
    print("-" * 50)
    print("✅ Deterministic mapping complete! Processed files updated.")

if __name__ == "__main__":
    run_deterministic_mapping()