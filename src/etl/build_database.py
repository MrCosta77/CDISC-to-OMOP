import duckdb
import sys
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))
from src.utils.config import DB_PATH

from src.omop.cdm54 import (
    CDM_RELEASE,
    SPEC_SHA256,
    CDM_VERSION,
    create_table_sql,
    duckdb_type,
    ensure_empty_cdm_tables,
    load_table_specs,
    quote_identifier,
    record_schema_manifest,
    validate_table_schema,
)
from src.omop.type_concepts import TYPE_CONCEPT_FIELDS


PUBLICATION_FILES = {
    "person": "PERSON.csv",
    "observation_period": "OBSERVATION_PERIOD.csv",
    "visit_occurrence": "VISIT_OCCURRENCE.csv",
    "condition_occurrence": "CONDITION_OCCURRENCE.csv",
    "drug_exposure": "DRUG_EXPOSURE.csv",
    "measurement": "MEASUREMENT.csv",
}

DOMAIN_FIELDS = {
    ("person", "gender_concept_id"): "Gender",
    ("person", "race_concept_id"): "Race",
    ("person", "ethnicity_concept_id"): "Ethnicity",
    ("visit_occurrence", "visit_concept_id"): "Visit",
    ("condition_occurrence", "condition_concept_id"): "Condition",
    ("drug_exposure", "drug_concept_id"): "Drug",
    ("measurement", "measurement_concept_id"): "Measurement",
    **{
        (table, field): "Type Concept"
        for table, field in TYPE_CONCEPT_FIELDS.items()
    },
}


def _table_columns(con, table):
    return {
        row[1]
        for row in con.execute(
            f"PRAGMA table_info({quote_identifier(table)})"
        ).fetchall()
    }


def _load_staging_table(con, table, csv_path):
    staging = f"stg_{table}"
    con.execute(f"DROP TABLE IF EXISTS {quote_identifier(staging)}")
    con.execute(
        f"""
        CREATE TEMP TABLE {quote_identifier(staging)} AS
        SELECT *
        FROM read_csv(?, header = TRUE, all_varchar = TRUE, nullstr = '')
        """,
        [str(csv_path)],
    )
    return staging


def _field_expression(field, staging_columns):
    target_type = duckdb_type(field.datatype)
    if field.name not in staging_columns:
        if field.required:
            raise ValueError(
                f"Missing required OMOP CDM {CDM_VERSION} field "
                f"{field.table}.{field.name} in the processed CSV."
            )
        if field.foreign_key and (field.fk_table or "").upper() == "CONCEPT":
            return f"CAST(0 AS {target_type})"
        return f"CAST(NULL AS {target_type})"

    source = quote_identifier(field.name)
    if target_type.startswith("VARCHAR"):
        return f"CAST(NULLIF({source}, '') AS {target_type})"
    value = f"CAST(NULLIF(TRIM({source}), '') AS {target_type})"
    if not field.required and field.foreign_key and (
        field.fk_table or ""
    ).upper() == "CONCEPT":
        return f"COALESCE({value}, CAST(0 AS {target_type}))"
    return value


def _stage_into_candidate(con, table, csv_path):
    staging = _load_staging_table(con, table, csv_path)
    staging_columns = _table_columns(con, staging)
    fields = load_table_specs()[table]
    missing_required = [
        field.name
        for field in fields
        if field.required and field.name not in staging_columns
    ]
    if missing_required:
        raise ValueError(
            f"{csv_path.name} is missing required OMOP fields: "
            + ", ".join(missing_required)
        )

    candidate = f"publish_{table}"
    con.execute(f"DROP TABLE IF EXISTS {quote_identifier(candidate)}")
    con.execute(create_table_sql(table, candidate))
    target_columns = ", ".join(quote_identifier(field.name) for field in fields)
    expressions = ",\n            ".join(
        _field_expression(field, staging_columns) for field in fields
    )
    con.execute(f"""
        INSERT INTO {quote_identifier(candidate)} ({target_columns})
        SELECT
            {expressions}
        FROM {quote_identifier(staging)}
    """)

    staged_count = con.execute(
        f"SELECT COUNT(*) FROM {quote_identifier(staging)}"
    ).fetchone()[0]
    candidate_count = con.execute(
        f"SELECT COUNT(*) FROM {quote_identifier(candidate)}"
    ).fetchone()[0]
    if staged_count != candidate_count:
        raise ValueError(
            f"Row-count mismatch for {table}: staged={staged_count}, "
            f"candidate={candidate_count}."
        )
    validate_table_schema(con, table, candidate)
    return candidate, candidate_count


def _require_no_orphans(con, child, child_key, parent, parent_key, nullable=False):
    null_filter = f"c.{quote_identifier(child_key)} IS NOT NULL AND " if nullable else ""
    count = con.execute(f"""
        SELECT COUNT(*)
        FROM {quote_identifier(child)} c
        LEFT JOIN {quote_identifier(parent)} p
          ON c.{quote_identifier(child_key)} = p.{quote_identifier(parent_key)}
        WHERE {null_filter}p.{quote_identifier(parent_key)} IS NULL
    """).fetchone()[0]
    if count:
        raise ValueError(
            f"Relational validation failed: {count} {child}.{child_key} values "
            f"do not reference {parent}.{parent_key}."
        )


def _require_valid_date_range(con, table, start_field, end_field, nullable_end=False):
    end_filter = f"{quote_identifier(end_field)} IS NOT NULL AND " if nullable_end else ""
    count = con.execute(f"""
        SELECT COUNT(*)
        FROM {quote_identifier(table)}
        WHERE {end_filter}{quote_identifier(end_field)} < {quote_identifier(start_field)}
    """).fetchone()[0]
    if count:
        raise ValueError(
            f"Date validation failed: {count} rows in {table} end before they start."
        )


def _validate_concepts(con, candidates):
    concept_fields = []
    requested_ids = set()
    for logical_table, physical_table in candidates.items():
        for field in load_table_specs()[logical_table]:
            if field.foreign_key and (field.fk_table or "").upper() == "CONCEPT":
                concept_fields.append((logical_table, physical_table, field.name))
                requested_ids.update(
                    int(row[0])
                    for row in con.execute(f"""
                        SELECT DISTINCT {quote_identifier(field.name)}
                        FROM {quote_identifier(physical_table)}
                        WHERE {quote_identifier(field.name)} IS NOT NULL
                          AND {quote_identifier(field.name)} <> 0
                    """).fetchall()
                )
    if not requested_ids:
        return

    placeholders = ", ".join("?" for _ in requested_ids)
    rows = con.execute(f"""
        SELECT CAST(concept_id AS BIGINT), domain_id, standard_concept,
               invalid_reason,
               CURRENT_DATE BETWEEN valid_start_date AND valid_end_date
        FROM concept
        WHERE CAST(concept_id AS BIGINT) IN ({placeholders})
    """, sorted(requested_ids)).fetchall()
    concepts = {
        int(concept_id): (
            domain_id,
            standard_concept,
            invalid_reason,
            currently_valid,
        )
        for (
            concept_id,
            domain_id,
            standard_concept,
            invalid_reason,
            currently_valid,
        ) in rows
    }
    missing = sorted(requested_ids.difference(concepts))
    if missing:
        raise ValueError(f"OMOP concept references do not exist: {missing}")

    for logical_table, physical_table, field_name in concept_fields:
        expected_domain = DOMAIN_FIELDS.get((logical_table, field_name))
        if not expected_domain:
            continue
        ids = {
            int(row[0])
            for row in con.execute(f"""
                SELECT DISTINCT {quote_identifier(field_name)}
                FROM {quote_identifier(physical_table)}
                WHERE {quote_identifier(field_name)} IS NOT NULL
                  AND {quote_identifier(field_name)} <> 0
            """).fetchall()
        }
        invalid = [
            concept_id
            for concept_id in ids
            if concepts[concept_id][0] != expected_domain
            or concepts[concept_id][1] != "S"
            or concepts[concept_id][2] not in {None, ""}
            or not concepts[concept_id][3]
        ]
        if invalid:
            raise ValueError(
                f"{logical_table}.{field_name} contains invalid or wrong-domain "
                f"Standard Concepts: {sorted(invalid)}"
            )


def _validate_candidates(con, candidates):
    person = candidates["person"]
    visit = candidates["visit_occurrence"]
    for table in (
        "observation_period",
        "visit_occurrence",
        "condition_occurrence",
        "drug_exposure",
        "measurement",
    ):
        _require_no_orphans(
            con, candidates[table], "person_id", person, "person_id"
        )
    for table in ("condition_occurrence", "drug_exposure", "measurement"):
        _require_no_orphans(
            con,
            candidates[table],
            "visit_occurrence_id",
            visit,
            "visit_occurrence_id",
            nullable=True,
        )

    _require_valid_date_range(
        con,
        candidates["observation_period"],
        "observation_period_start_date",
        "observation_period_end_date",
    )
    _require_valid_date_range(
        con, visit, "visit_start_date", "visit_end_date"
    )
    visits_outside_period = con.execute(f"""
        SELECT COUNT(*)
        FROM {quote_identifier(visit)} v
        WHERE NOT EXISTS (
            SELECT 1
            FROM {quote_identifier(candidates['observation_period'])} o
            WHERE o.person_id = v.person_id
              AND v.visit_start_date >= o.observation_period_start_date
              AND v.visit_end_date <= o.observation_period_end_date
        )
    """).fetchone()[0]
    if visits_outside_period:
        raise ValueError(
            "Temporal validation failed: "
            f"{visits_outside_period} visits fall outside the observation period."
        )
    _require_valid_date_range(
        con,
        candidates["condition_occurrence"],
        "condition_start_date",
        "condition_end_date",
        nullable_end=True,
    )
    _require_valid_date_range(
        con,
        candidates["drug_exposure"],
        "drug_exposure_start_date",
        "drug_exposure_end_date",
    )
    _validate_concepts(con, candidates)

def build_omop_database(db_path=DB_PATH, processed_dir=None):
    print("🗄️ STARTING OMOP CDM 5.4 DATABASE PUBLICATION")
    print("-" * 70)
    print(f"Connecting to DuckDB at: {db_path}")
    processed_dir = Path(processed_dir or PROJECT_ROOT / "data" / "processed")
    paths = {
        table: processed_dir / filename
        for table, filename in PUBLICATION_FILES.items()
    }
    missing_files = [str(path) for path in paths.values() if not path.is_file()]
    if missing_files:
        raise FileNotFoundError(
            "Cannot publish an incomplete OMOP database. Missing processed files:\n- "
            + "\n- ".join(missing_files)
        )

    with duckdb.connect(str(db_path)) as con:
        con.execute("BEGIN TRANSACTION")
        try:
            ensure_empty_cdm_tables(con, exclude=PUBLICATION_FILES)
            record_schema_manifest(con)
            candidates = {}
            counts = {}
            for table, csv_path in paths.items():
                print(f"📦 Staging and validating {csv_path.name}...")
                candidate, count = _stage_into_candidate(con, table, csv_path)
                candidates[table] = candidate
                counts[table] = count

            _validate_candidates(con, candidates)

            for table in reversed(PUBLICATION_FILES):
                con.execute(f"DROP TABLE IF EXISTS {quote_identifier(table)}")
            for table, candidate in candidates.items():
                con.execute(
                    f"ALTER TABLE {quote_identifier(candidate)} "
                    f"RENAME TO {quote_identifier(table)}"
                )
                validate_table_schema(con, table)
                print(f"   ✅ Published {counts[table]} records to {table}.")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

    print("\n" + "=" * 70)
    print("🏆 OMOP CDM 5.4 DATABASE PUBLISHED TRANSACTIONALLY 🏆")
    print("All populated tables match the pinned OHDSI field contract.")
    print("=" * 70 + "\n")


def validate_published_database(db_path=DB_PATH):
    with duckdb.connect(str(db_path), read_only=True) as con:
        for table in load_table_specs():
            validate_table_schema(con, table)
        manifest = con.execute("""
            SELECT cdm_version, source_release, specification_sha256
            FROM cdm_schema_manifest
            WHERE cdm_version = ?
        """, [CDM_VERSION]).fetchone()
        if manifest != (CDM_VERSION, CDM_RELEASE, SPEC_SHA256):
            raise ValueError("The OMOP CDM schema manifest is missing or invalid.")
        candidates = {table: table for table in PUBLICATION_FILES}
        _validate_candidates(con, candidates)
        counts = {
            table: con.execute(
                f"SELECT COUNT(*) FROM {quote_identifier(table)}"
            ).fetchone()[0]
            for table in PUBLICATION_FILES
        }
    return {
        "cdm_version": CDM_VERSION,
        "source_release": CDM_RELEASE,
        "schema_table_count": len(load_table_specs()),
        "row_counts": counts,
    }

if __name__ == "__main__":
    build_omop_database()
