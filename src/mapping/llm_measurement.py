import pandas as pd
import duckdb
import ollama
import os
import sys
import re
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))
from src.utils.config import  DB_PATH, MODEL_NAME
from src.mapping.llm_shared import get_candidates_from_db_safe, calculate_confidence_score

def ask_llm_to_pick(raw_term, candidates):
    """Prompts the local LLM to select the best matching LOINC ID from the candidates."""
    if not candidates:
        return 0

    candidates_text = "\n".join([f"ID: {row[0]} | Name: {row[1]}" for row in candidates])
    
    system_prompt = """
    You are a highly skilled Clinical Data Scientist specializing in the OMOP Common Data Model.
    Your task is to map a raw clinical trial measurement, lab test, or vital sign to the best matching standard LOINC concept from a provided list.
    
    CRITICAL RULES:
    1. Reply ONLY with the integer ID of the best match.
    2. Do NOT include any explanations, markdown, or extra text.
    3. If none of the candidates are a clinically valid match for the raw term, reply with 0.
    """
    
    user_prompt = f"""
    Raw Clinical Term: "{raw_term}"
    
    Candidate Standard Concepts:
    {candidates_text}
    
    Return ONLY the ID of the best match.
    """
    
    try:
        response = ollama.chat(
            model=MODEL_NAME,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt}
            ],
            options={'temperature': 0.0} # Strict and deterministic
        )
        
        result_text = response['message']['content'].strip()
        match = re.search(r'\d+', result_text)
        
        if match:
            chosen_id = int(match.group())
            
            # The LLM correctly rejected the candidates based on Rule 3
            if chosen_id == 0:
                return 0
                
            # 🛡️ SECURITY GATE: Ensure the LLM didn't hallucinate an ID
            candidate_ids = [int(c[0]) for c in candidates]
            
            if chosen_id in candidate_ids:
                return chosen_id
            else:
                print(f"   ⚠️ Warning: LLM actually hallucinated ID {chosen_id} (not in candidates). Rejecting.")
                return 0
                
        return 0
        
    except Exception as e:
        print(f"⚠️ LLM Request Failed for '{raw_term}': {e}")
        return 0

def run_llm_measurement_mapping():
    print(f"🔬 STARTING AI SEMANTIC MAPPING FOR MEASUREMENTS (MODEL: {MODEL_NAME})")
    print("-" * 70)
    
    meas_path = os.path.join(PROJECT_ROOT, "data", "processed", "MEASUREMENT.csv")
    
    try:
        df_meas = pd.read_csv(meas_path)
    except FileNotFoundError:
        print("❌ Error: MEASUREMENT.csv not found.")
        return

    # Identify orphans
    unmapped_mask = df_meas['measurement_concept_id'] == 0
    orphan_terms = df_meas[unmapped_mask]['measurement_source_value'].dropna().unique()
    
    if len(orphan_terms) == 0:
        print("✅ No unmapped measurements found! Everything is already standard.")
        return
        
    print(f"Found {len(orphan_terms)} orphan clinical terms. Handing over to AI...")
    
    mapping_dict = {}
    with duckdb.connect(DB_PATH) as con:
        for term in orphan_terms:
            print(f"\n🔍 Processing: '{term}'")
            candidates = get_candidates_from_db_safe(term, con, 'Measurement')
            
            if candidates:
                print(f"   - Retrieved {len(candidates)} candidates from DuckDB. Asking LLM...")
                chosen_id = ask_llm_to_pick(term, candidates)
                
                if chosen_id != 0:
                    chosen_name = next((c[1] for c in candidates if int(c[0]) == chosen_id), "Unknown")
                    print(f"   ✅ AI Mapped: {term} ➔ {chosen_name} ({chosen_id})")
                    mapping_dict[term] = chosen_id
                else:
                    print(f"   ⚠️ AI decided no candidates were a good match. Left as 0.")
            else:
                print(f"   ⚠️ DuckDB found no keyword candidates. Left as 0.")

    # Apply the AI mappings to the dataframe
    if mapping_dict:
        mask = (df_meas['measurement_concept_id'] == 0) & (df_meas['measurement_source_value'].isin(mapping_dict.keys()))
        
        # Grab rows for audit trail
        rows_to_audit = df_meas[mask][['measurement_id', 'measurement_source_value']]
        
        # Update CSV
        df_meas.loc[mask, 'measurement_concept_id'] = df_meas.loc[mask, 'measurement_source_value'].map(mapping_dict)
        df_meas['measurement_concept_id'] = df_meas['measurement_concept_id'].astype('Int64')
        df_meas.to_csv(meas_path, index=False)
        
        # Write Provenance to DuckDB
        with duckdb.connect(DB_PATH) as con:
            try:
                vocab_version = con.execute("SELECT vocabulary_version FROM vocabulary WHERE vocabulary_id = 'None'").fetchone()[0]
            except duckdb.CatalogException:
                vocab_version = 'Athena_Standard'
                
            for _, row in rows_to_audit.iterrows():
                term = row['measurement_source_value'] # <-- Nome da coluna corrigido
                chosen_id = int(mapping_dict[term])
                
                # Fetch the exact name the LLM picked to calculate the score
                chosen_name = con.execute("SELECT concept_name FROM concept WHERE concept_id = ?", [chosen_id]).fetchone()[0]
                
                real_score = calculate_confidence_score(term, chosen_name)
                
                con.execute("""
                    INSERT INTO mapping_provenance (
                        target_table, target_id, source_value, normalized_value,
                        assigned_concept_id, mapping_method, score, model_name,
                        vocabulary_version, reviewed_by
                    ) VALUES (
                        'measurement', ?, ?, ?, ?, 'llm_zero_shot', ?, ?, ?, 'Pending_Human_Review'
                    )
                """, (
                    int(row['measurement_id']), # <-- ID corrigido
                    term, 
                    term, 
                    chosen_id, 
                    real_score, 
                    MODEL_NAME, 
                    vocab_version
                ))
                
        print("\n" + "-" * 70)
        print(f"💾 File updated: MEASUREMENT.csv")
        print("✅ Provenance Audit successfully updated in DuckDB!")
        print(f"🏆 AI successfully resolved {len(mapping_dict)} out of {len(orphan_terms)} orphan measurements!")
    else:
        print("\n" + "-" * 70)
        print("📉 AI could not confidently map any of the orphan terms.")

if __name__ == "__main__":
    run_llm_measurement_mapping()