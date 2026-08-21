import sys
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.omop.cdm54 import (
    CDM_RELEASE,
    CDM_VERSION,
    ensure_empty_cdm_tables,
    record_schema_manifest,
)
from src.utils.config import DB_PATH


def setup_cdm_schema(db_path=DB_PATH):
    print(f"⚙️ INSTALLING OMOP CDM {CDM_VERSION} SCHEMA ({CDM_RELEASE})")
    print("-" * 60)
    with duckdb.connect(str(db_path)) as con:
        con.execute("BEGIN TRANSACTION")
        try:
            ensure_empty_cdm_tables(con)
            record_schema_manifest(con)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    print("✅ The 39-table OMOP CDM 5.4 contract is installed.")


if __name__ == "__main__":
    setup_cdm_schema()
