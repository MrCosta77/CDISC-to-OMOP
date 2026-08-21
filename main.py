import subprocess
import sys
import time
import os
from pathlib import Path

# Setup paths to ensure imports work perfectly
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.append(str(PROJECT_ROOT))

# 1. IMPORT OUR PROFESSIONAL LOGGER
from src.utils.logger import get_logger
from src.utils.run_context import (
    RUN_ID_ENV,
    collect_output_counts,
    finish_pipeline_run,
    generate_run_id,
    start_pipeline_run,
    validate_required_inputs,
)

# 2. INITIALIZE THE ORCHESTRATOR LOGGER
logger = get_logger("Orchestrator")

def run_script(script_path, step_name, run_id):
    logger.info(f"{'='*70}")
    logger.info(f"🚀 RUNNING: {step_name}")
    logger.info(f"📄 Script:  {script_path}")
    logger.info(f"🆔 Run ID:  {run_id}")
    logger.info(f"{'='*70}")
    
    start_time = time.time()
    
    try:
        # Executes the script using the same Python interpreter running main.py
        subprocess.run(
            [sys.executable, script_path],
            cwd=PROJECT_ROOT,
            env={
                **os.environ,
                RUN_ID_ENV: run_id,
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            },
            check=True,
        )
        elapsed = time.time() - start_time
        logger.info(f"✅ SUCCESS: '{step_name}' completed in {elapsed:.1f} seconds.\n")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ ERROR: '{step_name}' failed with exit code {e.returncode}.\n")
        raise
    except FileNotFoundError:
        logger.error(f"❌ ERROR: Script not found at {script_path}. Check your paths.\n")
        raise

def main():
    run_id = generate_run_id()
    os.environ[RUN_ID_ENV] = run_id
    logger.info("🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥")
    logger.info("      CDISC TO OMOP - FULL ORCHESTRATOR")
    logger.info(f"      RUN ID: {run_id}")
    logger.info("🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥")

    total_start = time.time()
    try:
        start_pipeline_run(run_id)
        validate_required_inputs()

        steps = [
            ("src/utils/setup_cdm_schema.py", "0. Install OMOP CDM 5.4 Schema"),
            ("src/utils/setup_vocab.py", "0. Setup OMOP Vocabularies"),
            ("src/utils/setup_audit.py", "0b. Setup Audit and Provenance"),
            ("src/etl/person.py", "1. Extract Demographics (DM)"),
            ("src/etl/condition.py", "2. Extract Conditions (AE + MH)"),
            ("src/etl/drug.py", "3. Extract Medications (EX + CM)"),
            ("src/etl/measurement.py", "4. Extract Measurements (LB + VS + EG)"),
            ("src/etl/observation_period.py", "5. Calculate Observation Periods"),
            ("src/etl/visit.py", "6. Extract Actual Visits (SV)"),
            ("src/etl/link_visits.py", "7. Link Events to Visits"),
            ("src/mapping/deterministic_mapping.py", "8. Deterministic Mapping"),
            (
                "src/mapping/apply_approved_mappings.py",
                "8b. Apply Human-Approved Mappings",
            ),
            ("src/mapping/llm_condition.py", "9. AI Proposals (Conditions)"),
            ("src/mapping/llm_drug.py", "10. AI Proposals (Drugs)"),
            ("src/mapping/llm_measurement.py", "11. AI Proposals (Measurements)"),
            ("src/etl/build_database.py", "12. Build Unified DuckDB Database"),
        ]
        for script_path, step_name in steps:
            run_script(script_path, step_name, run_id)

        output_counts = collect_output_counts()
        finish_pipeline_run(run_id, "SUCCESS", output_counts=output_counts)
        total_elapsed = time.time() - total_start
        logger.info(f"🎉 PIPELINE FULLY COMPLETED IN {total_elapsed:.1f}s! 🎉")
        logger.info(f"Run {run_id} published successfully.\n")
    except BaseException as exc:
        try:
            finish_pipeline_run(run_id, "FAILED", error_message=str(exc))
        except Exception:
            logger.exception("Could not persist the FAILED run status.")
        logger.exception(f"Pipeline run {run_id} failed.")
        raise

if __name__ == "__main__":
    main()
