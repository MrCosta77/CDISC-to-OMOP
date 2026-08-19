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
from src.utils.config import DB_PATH, MODEL_NAME

def get_candidates_from_db(term, con):
    """Fetches potential standard concepts from DuckDB using keyword matching."""
    # Extract significant words (length > 3) to build a flexible search
    words = [w for w in re.split(r'\W+', term) if len(w) > 3]
    if not words:
        words = [term] # Fallback to the whole string if words are short
        
    # Build SQL LIKE conditions
    conditions = " OR ".join([f"LOWER(concept_name) LIKE '%{w.lower()}%'" for w in words])
    
    query = f"""
        SELECT concept_id, concept_name 
        FROM concept 
        WHERE domain_id = 'Condition' 
          AND standard_concept = 'S' 
          AND ({conditions})
        ORDER BY LENGTH(concept_name) ASC
        LIMIT 15
    """
    return con.execute(query).fetchall()

def ask_llm_to_pick(raw_term, candidates):
    """Prompts the local LLM to select the best matching concept ID from the candidates."""
    if not candidates:
        return 0

    # Format candidates into a readable list for the LLM
    candidates_text = "\n".join([f"ID: {row[0]} | Name: {row[1]}" for row in candidates])
    
    system_prompt = """
    You are a highly skilled Clinical Data Scientist specializing in the OMOP Common Data Model.
    Your task is to map a raw clinical trial condition to the best matching standard SNOMED concept from a provided list.
    
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
            options={'temperature': 0.0} # Strict and deterministic reasoning
        )
        
        result_text = response['message']['content'].strip()
        match = re.search(r'\d+', result_text)
        
        if match:
            chosen_id = int(match.group())
            
            # 🛡️ SECURITY GATE: Ensure the LLM didn't hallucinate an ID
            candidate_ids = [int(c[0]) for c in candidates]
            
            if chosen_id in candidate_ids:
                return chosen_id
            else:
                print(f"   ⚠️ Warning: LLM hallucinated ID {chosen_id} (not in candidates). Rejecting.")
                return 0
                
        return 0
        
    except Exception as e:
        print(f"⚠️ LLM Request Failed for '{raw_term}': {e}")
        return 0

def run_llm_condition_mapping():
    print(f"🧠 STARTING AI SEMANTIC MAPPING FOR CONDITIONS (MODEL: {MODEL_NAME})")
    print("-" * 70)
    
    condition_path = os.path.join(PROJECT_ROOT, "data", "processed", "CONDITION_OCCURRENCE.csv")
    
    try:
        df_cond = pd.read_csv(condition_path)
    except FileNotFoundError:
        print("❌ Error: CONDITION_OCCURRENCE.csv not found.")
        return

    # Identify orphans
    unmapped_mask = df_cond['condition_concept_id'] == 0
    orphan_terms = df_cond[unmapped_mask]['condition_source_value'].dropna().unique()
    
    if len(orphan_terms) == 0:
        print("✅ No unmapped conditions found! Everything is already standard.")
        return
        
    print(f"Found {len(orphan_terms)} orphan clinical terms. Handing over to AI...")
    
    mapping_dict = {}
    with duckdb.connect(DB_PATH) as con:
        for term in orphan_terms:
            print(f"\n🔍 Processing: '{term}'")
            candidates = get_candidates_from_db(term, con)
            
            if candidates:
                print(f"   - Retrieved {len(candidates)} candidates from DuckDB. Asking LLM...")
                chosen_id = ask_llm_to_pick(term, candidates)
                
                if chosen_id != 0:
                    # Look up the chosen name to print a nice log
                    chosen_name = next((c[1] for c in candidates if int(c[0]) == chosen_id), "Unknown")
                    print(f"   ✅ AI Mapped: {term} ➔ {chosen_name} ({chosen_id})")
                    mapping_dict[term] = chosen_id
                else:
                    print(f"   ⚠️ AI decided no candidates were a good match. Left as 0.")
            else:
                print(f"   ⚠️ DuckDB found no keyword candidates. Left as 0.")

    # Apply the AI mappings to the dataframe
    if mapping_dict:
        # Create a boolean mask for rows that are currently 0 and have a newly discovered mapping
        mask = (df_cond['condition_concept_id'] == 0) & (df_cond['condition_source_value'].isin(mapping_dict.keys()))
        df_cond.loc[mask, 'condition_concept_id'] = df_cond.loc[mask, 'condition_source_value'].map(mapping_dict)
        
        # Ensure integers are preserved
        df_cond['condition_concept_id'] = df_cond['condition_concept_id'].astype('Int64')
        
        df_cond.to_csv(condition_path, index=False)
        print("\n" + "-" * 70)
        print(f"💾 File updated: CONDITION_OCCURRENCE.csv")
        print(f"🏆 AI successfully resolved {len(mapping_dict)} out of {len(orphan_terms)} orphan conditions!")
    else:
        print("\n" + "-" * 70)
        print("📉 AI could not confidently map any of the orphan terms.")

if __name__ == "__main__":
    run_llm_condition_mapping()