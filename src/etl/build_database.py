import duckdb
import os
import sys
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))
from src.utils.config import DB_PATH

def build_omop_database():
    print("🗄️ STARTING DATABASE BUILD PROCESS")
    print("-" * 70)
    print(f"Connecting to DuckDB at: {DB_PATH}")
    
    processed_dir = os.path.join(PROJECT_ROOT, "data", "processed")
    
    # Dictionary mapping the target OMOP table name to your generated CSV files
    tables = {
        "person": "PERSON.csv",
        "visit_occurrence": "VISIT_OCCURRENCE.csv",
        "condition_occurrence": "CONDITION_OCCURRENCE.csv",
        "drug_exposure": "DRUG_EXPOSURE.csv",
        "measurement": "MEASUREMENT.csv",
        "observation_period": "OBSERVATION_PERIOD.csv"
    }
    
    with duckdb.connect(DB_PATH) as con:
        for table_name, csv_file in tables.items():
            csv_path = os.path.join(processed_dir, csv_file)
            
            if not os.path.exists(csv_path):
                print(f"⚠️ Warning: {csv_file} not found. Skipping {table_name}.")
                continue
                
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

    print("\n" + "=" * 70)
    print("🏆 OMOP RELATIONAL DATABASE SUCCESSFULLY BUILT! 🏆")
    print("Your clinical data and OHDSI vocabularies are now united in a single SQL engine.")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    build_omop_database()