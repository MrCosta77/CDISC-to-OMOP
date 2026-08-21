import duckdb
import os
import sys
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))
from src.utils.config import DB_PATH

def build_omop_database(db_path=DB_PATH, processed_dir=None):
    print("🗄️ STARTING DATABASE BUILD PROCESS")
    print("-" * 70)
    print(f"Connecting to DuckDB at: {db_path}")
    
    processed_dir = processed_dir or os.path.join(PROJECT_ROOT, "data", "processed")
    
    # Dictionary mapping the target OMOP table name to your generated CSV files
    tables = {
        "person": "PERSON.csv",
        "visit_occurrence": "VISIT_OCCURRENCE.csv",
        "condition_occurrence": "CONDITION_OCCURRENCE.csv",
        "drug_exposure": "DRUG_EXPOSURE.csv",
        "measurement": "MEASUREMENT.csv",
        "observation_period": "OBSERVATION_PERIOD.csv"
    }
    
    missing_files = [
        os.path.join(processed_dir, csv_file)
        for csv_file in tables.values()
        if not os.path.exists(os.path.join(processed_dir, csv_file))
    ]
    if missing_files:
        raise FileNotFoundError(
            "Cannot publish an incomplete OMOP database. Missing processed files:\n- "
            + "\n- ".join(missing_files)
        )

    with duckdb.connect(str(db_path)) as con:
        con.execute("BEGIN TRANSACTION")
        try:
            for table_name, csv_file in tables.items():
                csv_path = os.path.join(processed_dir, csv_file)
                
                print(f"📦 Importing {csv_file} into table '{table_name}'...")
            
            # Drop table if it exists to ensure perfect idempotency
                con.execute(f"DROP TABLE IF EXISTS {table_name}")
            
            # Create table directly and ingest the CSV data instantly
                con.execute(f"""
                    CREATE TABLE {table_name} AS
                    SELECT * FROM read_csv_auto('{csv_path}')
                """)
            
            # Verify the insertion
                count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                print(f"   ✅ Successfully loaded {count} records.")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

    print("\n" + "=" * 70)
    print("🏆 OMOP RELATIONAL DATABASE SUCCESSFULLY BUILT! 🏆")
    print("Your clinical data and OHDSI vocabularies are now united in a single SQL engine.")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    build_omop_database()
