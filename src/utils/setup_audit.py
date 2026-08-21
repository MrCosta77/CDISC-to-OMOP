import sys
import duckdb
from pathlib import Path
from datetime import datetime

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.utils.config import DB_PATH
from src.omop.cdm54 import create_table_sql, validate_table_schema
from src.utils.run_context import ensure_audit_schema


def setup_audit_tables(db_path=DB_PATH):
    print("⚙️ STARTING AUDIT & METADATA SETUP")
    print("-" * 50)
    
    with duckdb.connect(str(db_path)) as con:
        con.execute("BEGIN TRANSACTION")
        try:
            ensure_audit_schema(con)
            print("✅ 'mapping_provenance' table verified/created successfully!")

            # CDM_SOURCE is generated from the pinned OHDSI field contract.
            con.execute("DROP TABLE IF EXISTS cdm_source")
            con.execute(create_table_sql("cdm_source"))
        
            # Tentar ler a versão do vocabulário dinamicamente
            vocab_version = "Athena_Standard"
            try:
                res = con.execute(
                    "SELECT vocabulary_version FROM vocabulary "
                    "WHERE vocabulary_id = 'None'"
                ).fetchone()
                if res and res[0]:
                    vocab_version = res[0]
            except duckdb.CatalogException:
                pass

            current_date = datetime.now().strftime("%Y-%m-%d")
        
            con.execute("""
                INSERT INTO cdm_source (
                    cdm_source_name, cdm_source_abbreviation, cdm_holder,
                    source_description, source_documentation_reference,
                    cdm_etl_reference, source_release_date, cdm_release_date,
                    cdm_version, cdm_version_concept_id, vocabulary_version
                ) VALUES (
                    'CDISC to OMOP Clinical Trial',
                    'CDISC-OMOP',
                    'Clinical Data Engineer',
                    'Clinical trial data from CDISC SDTM standard mapped to OMOP CDM.',
                    'CDISC SDTM IG',
                    'https://github.com/MrCosta77/CDISC-to-OMOP',
                    ?, ?, '5.4', 756265, ?
                )
            """, (current_date, current_date, vocab_version))
            validate_table_schema(con, "cdm_source")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

        print("✅ 'cdm_source' table verified/created successfully!")


if __name__ == "__main__":
    setup_audit_tables()
