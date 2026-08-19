import subprocess
import sys
import time

def run_script(script_path, step_name):
    print(f"\n{'='*70}")
    print(f"🚀 RUNNING: {step_name}")
    print(f"📄 Script:  {script_path}")
    print(f"{'='*70}\n")
    
    start_time = time.time()
    
    try:
        # Executes the script using the same Python interpreter running main.py
        subprocess.run([sys.executable, script_path], check=True)
        elapsed = time.time() - start_time
        print(f"\n✅ SUCCESS: '{step_name}' completed in {elapsed:.1f} seconds.")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ ERROR: '{step_name}' failed with exit code {e.returncode}.")
        sys.exit(1)
    except FileNotFoundError:
        print(f"\n❌ ERROR: Script not found at {script_path}. Check your paths.")
        sys.exit(1)

def main():
    print("\n🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥")
    print("      CDISC TO OMOP - FULL ORCHESTRATOR")
    print("🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥\n")

    total_start = time.time()

    # ---------------------------------------------------------
    # PHASE 1: VOCABULARIES SETUP
    # ---------------------------------------------------------
    run_script("src/utils/setup_vocab.py", "0. Setup OMOP Vocabularies")

    # ---------------------------------------------------------
    # PHASE 2: STRUCTURAL ETL (CDISC -> OMOP)
    # ---------------------------------------------------------
    run_script("src/etl/person.py", "1. Extract Demographics (DM)")
    run_script("src/etl/condition.py", "2. Extract Conditions (AE + MH)")
    run_script("src/etl/drug.py", "3. Extract Medications (EX + CM)")
    run_script("src/etl/measurement.py", "4. Extract Measurements (LB + VS + EG)")
    run_script("src/etl/observation_period.py", "5. Calculate Observation Periods")
    run_script("src/etl/visit.py", "6. Derive Visits from Events")
    run_script("src/etl/link_visits.py", "7. Link Events to Visits")
    
    # ---------------------------------------------------------
    # PHASE 3: SEMANTIC MAPPING (DETERMINISTIC + AI RAG)
    # ---------------------------------------------------------
    run_script("src/mapping/deterministic_mapping.py", "8. Deterministic Mapping (OHDSI Vocabularies)")
    run_script("src/mapping/llm_condition.py", "9. AI Semantic Mapping (Conditions)")
    run_script("src/mapping/llm_drug.py", "10. AI Semantic Mapping (Drugs)")

    # ---------------------------------------------------------
    # PHASE 4: DATABASE CONSTRUCTION
    # ---------------------------------------------------------
    run_script("src/etl/build_database.py", "11. Build Unified DuckDB Database")
    
    total_elapsed = time.time() - total_start
    print(f"\n🎉 PIPELINE FULLY COMPLETED IN {total_elapsed:.1f}s! 🎉")
    print("Database is now structured, domain-routed, and AI-mapped.\n")

if __name__ == "__main__":
    main()