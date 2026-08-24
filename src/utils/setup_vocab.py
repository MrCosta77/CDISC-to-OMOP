import sys
import duckdb
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.utils.config import DB_PATH, VOCAB_DIR, VOCAB_MANIFEST_PATH
from src.utils.vocabulary_identity import validate_vocabulary_manifest
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


VOCABULARY_TABLE_FILES = {
    "concept": "CONCEPT.csv",
    "concept_relationship": "CONCEPT_RELATIONSHIP.csv",
    "vocabulary": "VOCABULARY.csv",
    "domain": "DOMAIN.csv",
    "concept_class": "CONCEPT_CLASS.csv",
    "relationship": "RELATIONSHIP.csv",
}


def load_vocabularies(
    db_path=DB_PATH,
    vocab_dir=VOCAB_DIR,
    manifest_path=VOCAB_MANIFEST_PATH,
):
    print("⚙️ STARTING PINNED ATHENA VOCABULARY LOAD")
    print("-" * 50)

    vocab_dir = Path(vocab_dir)
    identity = validate_vocabulary_manifest(
        vocab_dir, manifest_path, verify_hashes=True
    )
    print(f"🔐 Verified Athena identity: {identity['version_label']}")
        
    with duckdb.connect(str(db_path)) as con:
        con.execute("BEGIN TRANSACTION")
        try:
            candidates = {}
            counts = {}
            for table, filename in VOCABULARY_TABLE_FILES.items():
                print(f"⏳ Loading {table.upper()} from {filename}...")
                candidate, count = _load_vocabulary_candidate(
                    con, table, vocab_dir / filename
                )
                candidates[table] = candidate
                counts[table] = count

            for table in reversed(VOCABULARY_TABLE_FILES):
                con.execute(f"DROP TABLE IF EXISTS {quote_identifier(table)}")
            for table, candidate in candidates.items():
                con.execute(
                    f"ALTER TABLE {quote_identifier(candidate)} "
                    f"RENAME TO {quote_identifier(table)}"
                )
                validate_table_schema(con, table)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        
    print("\n✅ Vocabularies successfully loaded into new DuckDB instance!")
    for table, count in counts.items():
        print(f" - {table.upper()}: {count:,} rows")
    print(f" - Database initialized at: {db_path}")

if __name__ == "__main__":
    load_vocabularies()
