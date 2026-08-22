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
from src.utils.config import DB_PATH, MODEL_NAME, CONFIDENCE_THRESHOLD
from src.mapping.llm_shared import get_candidates_from_db_safe, calculate_confidence_score
from src.mapping.review_store import (
    get_vocabulary_version,
    get_active_mapping_rule,
    record_mapping_decision,
)
from src.utils.run_context import require_run_id


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

def run_llm_condition_mapping():
    print(f"🧠 STARTING AI SEMANTIC MAPPING FOR CONDITIONS (MODEL: {MODEL_NAME})")
    print("-" * 70)
    
    run_id = require_run_id()
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
    
    proposed_count = 0
    low_confidence_count = 0
    unresolved_count = 0
    policy_count = 0
    with duckdb.connect(DB_PATH) as con:
        vocabulary_version = get_vocabulary_version(con)
        for term in orphan_terms:
            print(f"\n🔍 Processing: '{term}'")
            rule_status, _ = get_active_mapping_rule(
                con, "condition_occurrence", term
            )
            if rule_status == "APPROVED":
                print("   ↪ Active approval already exists; LLM skipped.")
                continue
            affected_ids = df_cond.loc[
                unmapped_mask & (df_cond['condition_source_value'] == term),
                'condition_occurrence_id',
            ].tolist()
            if rule_status == "REJECTED":
                record_mapping_decision(
                    con, run_id=run_id,
                    target_table="condition_occurrence", source_value=term,
                    proposed_concept_id=0, score=0.0, model_name=MODEL_NAME,
                    vocabulary_version=vocabulary_version,
                    affected_target_ids=affected_ids,
                    minimum_score=CONFIDENCE_THRESHOLD,
                )
                policy_count += 1
                print("   🔒 Active rejection reused; retrieval and LLM skipped.")
                continue
            candidates = get_candidates_from_db_safe(term, con, 'Condition')
            chosen_id = 0
            chosen_name = None
            if candidates:
                print(f"   - Retrieved {len(candidates)} candidates from DuckDB. Asking LLM...")
                chosen_id = ask_llm_to_pick(term, candidates)
                
                if chosen_id != 0:
                    chosen_name = next((c[1] for c in candidates if int(c[0]) == chosen_id), "Unknown")
                    print(f"   📝 AI Proposed: {term} ➔ {chosen_name} ({chosen_id})")
                else:
                    print("   ⚠️ AI proposed no valid match.")
            else:
                print("   ⚠️ DuckDB found no keyword candidates.")

            score = calculate_confidence_score(term, chosen_name) if chosen_id else 0.0
            record_mapping_decision(
                con,
                run_id=run_id,
                target_table="condition_occurrence",
                source_value=term,
                proposed_concept_id=chosen_id,
                score=score,
                model_name=MODEL_NAME,
                vocabulary_version=vocabulary_version,
                affected_target_ids=affected_ids,
                minimum_score=CONFIDENCE_THRESHOLD,
            )
            if chosen_id and score >= CONFIDENCE_THRESHOLD:
                proposed_count += 1
            elif chosen_id:
                low_confidence_count += 1
                print(
                    f"   ⚠️ Candidate retained for review below threshold "
                    f"({score:.2f} < {CONFIDENCE_THRESHOLD:.2f})."
                )
            else:
                unresolved_count += 1

    print("\n" + "-" * 70)
    print(
        f"📝 Stored {proposed_count} proposals, {low_confidence_count} low-"
        f"confidence candidates, {unresolved_count} unresolved terms and "
        f"{policy_count} policy rejections."
    )
    print("🔒 No pending LLM proposal was applied to CONDITION_OCCURRENCE.csv.")

if __name__ == "__main__":
    run_llm_condition_mapping()
