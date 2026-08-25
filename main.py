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
from src.utils.atomic_database import atomic_database_candidate
from src.utils.config import DB_PATH, PROCESSED_DIR
from src.utils.run_context import (
    RUN_ID_ENV,
    carry_forward_pipeline_history,
    collect_output_counts,
    collect_source_state,
    config_snapshot,
    finish_pipeline_run,
    generate_run_id,
    require_publishable_source_state,
    start_pipeline_run,
    validate_required_inputs,
)
from src.quality.validate_cdisc_inputs import validate_cdisc_inputs
from src.etl.build_database import validate_published_database

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
    source_state = collect_source_state()
    require_publishable_source_state(source_state)
    os.environ[RUN_ID_ENV] = run_id
    logger.info("🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥")
    logger.info("      CDISC TO OMOP - FULL ORCHESTRATOR")
    logger.info(f"      RUN ID: {run_id}")
    logger.info("🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥🏥")

    total_start = time.time()
    final_db_path = Path(DB_PATH).absolute()
    processed_run_dir = Path(PROCESSED_DIR).absolute() / run_id
    try:
        validate_required_inputs()
        input_counts = validate_cdisc_inputs()
        logger.info(f"CDISC input contracts accepted: {input_counts}")
        processed_run_dir.mkdir(parents=True, exist_ok=False)

        steps = [
            ("src/utils/setup_cdm_schema.py", "0. Install OMOP CDM 5.4 Schema"),
            ("src/utils/setup_vocab.py", "0. Setup OMOP Vocabularies"),
            ("src/utils/setup_audit.py", "0b. Setup Audit and Provenance"),
            (
                "src/mapping/sync_mapping_rules.py",
                "0c. Restore Versioned Human Mapping Rules",
            ),
            ("src/etl/care_site.py", "1. Extract Study Sites (DM)"),
            ("src/etl/person.py", "2. Extract Demographics (DM)"),
            ("src/etl/condition.py", "3. Extract Conditions (AE + MH)"),
            ("src/etl/drug.py", "4. Extract Medications (EX + CM)"),
            ("src/etl/measurement.py", "5. Extract Measurements (LB + VS + EG)"),
            ("src/etl/observation_period.py", "6. Calculate Observation Periods"),
            ("src/etl/visit.py", "7. Extract Actual Visits (SV)"),
            ("src/etl/link_visits.py", "8. Link Events to Visits"),
            (
                "src/etl/source_lineage.py",
                "8b. Build SDTM-to-OMOP Source Lineage",
            ),
            ("src/mapping/deterministic_mapping.py", "9. Deterministic Mapping"),
            (
                "src/mapping/apply_approved_mappings.py",
                "9b. Apply Human-Approved Mappings",
            ),
            ("src/mapping/llm_condition.py", "10. AI Proposals (Conditions)"),
            ("src/mapping/llm_drug.py", "11. AI Proposals (Drugs)"),
            ("src/mapping/llm_measurement.py", "12. AI Proposals (Measurements)"),
            ("src/etl/build_database.py", "13. Build Unified DuckDB Database"),
        ]
        with atomic_database_candidate(final_db_path, run_id) as candidate_path:
            previous_db_path = os.environ.get("DB_PATH")
            previous_processed_dir = os.environ.get("PROCESSED_DIR")
            os.environ["DB_PATH"] = str(candidate_path)
            os.environ["PROCESSED_DIR"] = str(processed_run_dir)
            run_started = False
            try:
                history_count = carry_forward_pipeline_history(
                    final_db_path, candidate_path
                )
                snapshot = config_snapshot()
                snapshot.update({
                    "publication_mode": "atomic_candidate",
                    "publication_target": str(final_db_path),
                    "candidate_path": str(candidate_path),
                    "processed_dir": str(processed_run_dir),
                    "carried_pipeline_run_count": history_count,
                })
                start_pipeline_run(
                    run_id,
                    db_path=candidate_path,
                    snapshot=snapshot,
                    source_state=source_state,
                )
                run_started = True
                for script_path, step_name in steps:
                    run_script(script_path, step_name, run_id)

                validate_published_database(candidate_path)
                output_counts = collect_output_counts(candidate_path)
                finish_pipeline_run(
                    run_id,
                    "SUCCESS",
                    output_counts=output_counts,
                    db_path=candidate_path,
                )
            except BaseException as exc:
                if run_started and candidate_path.is_file():
                    try:
                        finish_pipeline_run(
                            run_id,
                            "FAILED",
                            error_message=str(exc),
                            db_path=candidate_path,
                        )
                    except Exception:
                        logger.exception(
                            "Could not persist FAILED status in candidate database."
                        )
                raise
            finally:
                if previous_db_path is None:
                    os.environ.pop("DB_PATH", None)
                else:
                    os.environ["DB_PATH"] = previous_db_path
                if previous_processed_dir is None:
                    os.environ.pop("PROCESSED_DIR", None)
                else:
                    os.environ["PROCESSED_DIR"] = previous_processed_dir

        total_elapsed = time.time() - total_start
        logger.info(f"🎉 PIPELINE FULLY COMPLETED IN {total_elapsed:.1f}s! 🎉")
        logger.info(
            f"Run {run_id} atomically published to {final_db_path}.\n"
        )
    except BaseException as exc:
        logger.exception(f"Pipeline run {run_id} failed.")
        raise

if __name__ == "__main__":
    main()
