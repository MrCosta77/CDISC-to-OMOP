import sys
import duckdb
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.utils.config import DB_PATH, VOCAB_DIR
from src.omop.cdm54 import (
    create_table_sql,
    duckdb_type,
    expected_columns,
    load_table_specs,
    quote_identifier,
    validate_table_schema,
)


def _load_vocabulary_candidate(con, table, csv_path):
    staging = f"vocab_stg_{table}"
    candidate = f"vocab_publish_{table}"
    con.execute(f"DROP TABLE IF EXISTS {quote_identifier(staging)}")
    con.execute(f"DROP TABLE IF EXISTS {quote_identifier(candidate)}")
    con.execute(
        f"""
        CREATE TEMP TABLE {quote_identifier(staging)} AS
        SELECT * FROM read_csv(
            ?, delim='\t', header=TRUE, quote='', escape='',
            nullstr='', all_varchar=TRUE
        )
        """,
        [str(csv_path)],
    )
    staging_columns = {
        row[1]
        for row in con.execute(
            f"PRAGMA table_info({quote_identifier(staging)})"
        ).fetchall()
    }
    missing = sorted(set(expected_columns(table)).difference(staging_columns))
    if missing:
        raise ValueError(
            f"{Path(csv_path).name} is missing official OMOP fields: "
            + ", ".join(missing)
        )

    con.execute(create_table_sql(table, candidate))
    fields = load_table_specs()[table]
    columns = ", ".join(quote_identifier(field.name) for field in fields)
    expressions = []
    for field in fields:
        source = quote_identifier(field.name)
        target_type = duckdb_type(field.datatype)
        if target_type.startswith("VARCHAR"):
            expressions.append(
                f"CAST(NULLIF({source}, '') AS {target_type})"
            )
        elif target_type == "DATE":
            expressions.append(
                "COALESCE("
                f"TRY_STRPTIME(NULLIF(TRIM({source}), ''), '%Y%m%d')::DATE, "
                f"TRY_CAST(NULLIF(TRIM({source}), '') AS DATE)"
                ")"
            )
        else:
            expressions.append(
                f"CAST(NULLIF(TRIM({source}), '') AS {target_type})"
            )
    con.execute(f"""
        INSERT INTO {quote_identifier(candidate)} ({columns})
        SELECT {", ".join(expressions)}
        FROM {quote_identifier(staging)}
    """)
    validate_table_schema(con, table, candidate)
    return candidate, con.execute(
        f"SELECT COUNT(*) FROM {quote_identifier(candidate)}"
    ).fetchone()[0]


def load_vocabularies(db_path=DB_PATH, vocab_dir=VOCAB_DIR):
    print("⚙️ STARTING VOCABULARY LOAD (CONCEPT & CONCEPT_RELATIONSHIP)")
    print("-" * 50)
    
    vocab_dir = Path(vocab_dir)
    concept_csv = vocab_dir / "CONCEPT.csv"
    rel_csv = vocab_dir / "CONCEPT_RELATIONSHIP.csv"
    
    if not concept_csv.is_file() or not rel_csv.is_file():
        raise FileNotFoundError(
            f"Could not find CONCEPT.csv and CONCEPT_RELATIONSHIP.csv in {vocab_dir}"
        )
        
    with duckdb.connect(str(db_path)) as con:
        con.execute("BEGIN TRANSACTION")
        try:
            print("⏳ Loading CONCEPT table (this may take a few seconds)...")
            concept_candidate, concept_count = _load_vocabulary_candidate(
                con, "concept", concept_csv
            )
            print("⏳ Loading CONCEPT_RELATIONSHIP table (the 'Maps to' bridge)...")
            relationship_candidate, rel_count = _load_vocabulary_candidate(
                con, "concept_relationship", rel_csv
            )

            con.execute("DROP TABLE IF EXISTS concept_relationship")
            con.execute("DROP TABLE IF EXISTS concept")
            con.execute(
                f"ALTER TABLE {quote_identifier(concept_candidate)} "
                "RENAME TO concept"
            )
            con.execute(
                f"ALTER TABLE {quote_identifier(relationship_candidate)} "
                "RENAME TO concept_relationship"
            )
            validate_table_schema(con, "concept")
            validate_table_schema(con, "concept_relationship")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        
    print("\n✅ Vocabularies successfully loaded into new DuckDB instance!")
    print(f" - CONCEPT: {concept_count:,} rows")
    print(f" - CONCEPT_RELATIONSHIP: {rel_count:,} rows")
    print(f" - Database initialized at: {db_path}")

if __name__ == "__main__":
    load_vocabularies()
