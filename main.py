import subprocess
import sys
import time
from pathlib import Path

# Setup paths to ensure imports work perfectly
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.append(str(PROJECT_ROOT))

# 1. IMPORT OUR PROFESSIONAL LOGGER
from src.utils.logger import get_logger

# 2. INITIALIZE THE ORCHESTRATOR LOGGER
logger = get_logger("Orchestrator")

def run_script(script_path, step_name):
    logger.info(f"{'='*70}")
    logger.info(f"🚀 RUNNING: {step_name}")
    logger.info(f"📄 Script:  {script_path}")
    logger.info(f"{'='*70}")
    
    start_time = time.time()
    
    try:
        # Executes the script using the same Python interpreter running main.py
        subprocess.run([sys.executable, script_path], check=True)
        elapsed = time.time() - start_time
        logger.info(f"✅ SUCCESS: '{step_name}' completed in {elapsed:.1f} seconds.\n")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ ERROR: '{step_name}' failed with exit code {e.returncode}.\n")
        sys.exit(1)
    except FileNotFoundError:
        logger.error(f"❌ ERROR: Script not found at {script_path}. Check your paths.\n")
        sys.exit(1)

def main():
    logger.info("🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥")
    logger.info("      CDISC TO OMOP - FULL ORCHESTRATOR")
    logger.info("🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥")

    total_start = time.time()

    # ---------------------------------------------------------
    # PHASE 1: VOCABULARIES SETUP
    # ---------------------------------------------------------
    run_script("src/utils/setup_vocab.py", "0. Setup OMOP Vocabularies")
    run_script("src/utils/setup_audit.py", "0b. Setup Audit and Provenance")

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
    run_script("src/mapping/llm_measurement.py", "11. AI Semantic Mapping (Measurements)")

    # ---------------------------------------------------------
    # PHASE 4: DATABASE CONSTRUCTION
    # ---------------------------------------------------------
    run_script("src/etl/build_database.py", "12. Build Unified DuckDB Database")
    
    total_elapsed = time.time() - total_start
    logger.info(f"🎉 PIPELINE FULLY COMPLETED IN {total_elapsed:.1f}s! 🎉")
    logger.info("Database is now structured, domain-routed, and AI-mapped.\n")

if __name__ == "__main__":
    main()