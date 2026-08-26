import duckdb
import sys
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))
from src.utils.config import DB_PATH, PROCESSED_DIR

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
from src.utils.run_context import require_run_id


PUBLICATION_FILES = {
    "care_site": "CARE_SITE.csv",
    "person": "PERSON.csv",
    "observation_period": "OBSERVATION_PERIOD.csv",
    "visit_occurrence": "VISIT_OCCURRENCE.csv",
    "condition_occurrence": "CONDITION_OCCURRENCE.csv",
    "drug_exposure": "DRUG_EXPOSURE.csv",
    "measurement": "MEASUREMENT.csv",
}
LINEAGE_FILE = "SOURCE_RECORD_LINEAGE.csv"
LINEAGE_TARGETS = {
    "person": "person_id",
    "observation_period": "observation_period_id",
    "visit_occurrence": "visit_occurrence_id",
    "condition_occurrence": "condition_occurrence_id",
    "drug_exposure": "drug_exposure_id",
    "measurement": "measurement_id",
}

DOMAIN_FIELDS = {
    ("person", "gender_concept_id"): "Gender",
    ("person", "race_concept_id"): "Race",
    ("person", "ethnicity_concept_id"): "Ethnicity",
    ("visit_occurrence", "visit_concept_id"): "Visit",
    ("condition_occurrence", "condition_concept_id"): "Condition",
    ("drug_exposure", "drug_concept_id"): "Drug",
    ("measurement", "measurement_concept_id"): "Measurement",
    ("measurement", "unit_concept_id"): "Unit",
    **{
        (table, field): "Type Concept"
        for table, field in TYPE_CONCEPT_FIELDS.items()
    },
}

# These optional OMOP fields carry source semantics and therefore must be
# explicit in this pipeline rather than silently defaulted by publication.
SOURCE_SEMANTIC_FIELDS = {
    "condition_occurrence": {"condition_source_concept_id"},
    "drug_exposure": {"drug_source_concept_id"},
    "measurement": {
        "measurement_source_concept_id",
        "unit_concept_id",
        "unit_source_concept_id",
        "unit_source_value",
        "value_source_value",
    },
}

SEMANTIC_CONCEPT_FIELDS = {
    "condition_occurrence": ("condition_occurrence_id", "condition_concept_id"),
    "drug_exposure": ("drug_exposure_id", "drug_concept_id"),
    "measurement": ("measurement_id", "measurement_concept_id"),
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
    missing_semantic = sorted(
        SOURCE_SEMANTIC_FIELDS.get(table, set()).difference(staging_columns)
    )
    if missing_semantic:
        raise ValueError(
            f"{csv_path.name} is missing explicit source-semantic fields: "
            + ", ".join(missing_semantic)
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


def _stage_lineage_candidate(con, csv_path):
    staging = _load_staging_table(con, "source_record_lineage", csv_path)
    required = {
        "run_id",
        "target_table",
        "target_id",
        "person_id",
        "source_domain",
        "source_file",
        "source_subject_id",
        "source_record_key",
        "source_value",
        "mapping_source_value",
        "source_end_date",
        "published_end_date",
        "end_date_derivation",
    }
    missing = sorted(required.difference(_table_columns(con, staging)))
    if missing:
        raise ValueError(
            f"{csv_path.name} is missing lineage fields: " + ", ".join(missing)
        )

    candidate = "publish_source_record_lineage"
    con.execute(f"DROP TABLE IF EXISTS {quote_identifier(candidate)}")
    con.execute(f"""
        CREATE TABLE {quote_identifier(candidate)} (
            run_id VARCHAR NOT NULL,
            target_table VARCHAR NOT NULL,
            target_id BIGINT NOT NULL,
            person_id BIGINT NOT NULL,
            source_domain VARCHAR NOT NULL,
            source_file VARCHAR NOT NULL,
            source_subject_id VARCHAR NOT NULL,
            source_record_key VARCHAR NOT NULL,
            source_value VARCHAR,
            mapping_source_value VARCHAR,
            source_end_date DATE,
            published_end_date DATE,
            end_date_derivation VARCHAR,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (target_table, target_id)
        )
    """)
    con.execute(f"""
        INSERT INTO {quote_identifier(candidate)} (
            run_id, target_table, target_id, person_id, source_domain,
            source_file, source_subject_id, source_record_key, source_value,
            mapping_source_value, source_end_date, published_end_date,
            end_date_derivation
        )
        SELECT
            NULLIF(run_id, ''),
            NULLIF(target_table, ''),
            CAST(NULLIF(TRIM(target_id), '') AS BIGINT),
            CAST(NULLIF(TRIM(person_id), '') AS BIGINT),
            NULLIF(source_domain, ''),
            NULLIF(source_file, ''),
            NULLIF(source_subject_id, ''),
            NULLIF(source_record_key, ''),
            NULLIF(source_value, ''),
            NULLIF(mapping_source_value, ''),
            CAST(NULLIF(source_end_date, '') AS DATE),
            CAST(NULLIF(published_end_date, '') AS DATE),
            NULLIF(end_date_derivation, '')
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
            "Row-count mismatch for source_record_lineage: "
            f"staged={staged_count}, candidate={candidate_count}."
        )
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


def _require_consistent_visit_link(
    con, event, event_date, visit, max_window_days=0
):
    count = con.execute(f"""
        SELECT COUNT(*)
        FROM {quote_identifier(event)} e
        LEFT JOIN {quote_identifier(visit)} v
          ON e.visit_occurrence_id = v.visit_occurrence_id
        WHERE e.visit_occurrence_id IS NOT NULL
          AND (
              v.visit_occurrence_id IS NULL
              OR v.person_id <> e.person_id
              OR e.{quote_identifier(event_date)} < v.visit_start_date - INTERVAL '{int(max_window_days)} days'
              OR e.{quote_identifier(event_date)} > v.visit_end_date + INTERVAL '{int(max_window_days)} days'
          )
    """).fetchone()[0]
    if count:
        raise ValueError(
            f"Visit-link validation failed: {count} rows in {event} reference "
            "a visit for another person or outside the event date."
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


def _validate_mapping_provenance(con, candidates, expected_run_id):
    """Require one matching audit row for every published semantic mapping."""
    if not str(expected_run_id or "").strip():
        raise ValueError("Mapping provenance validation requires a run_id.")

    mapped_count = sum(
        con.execute(f"""
            SELECT COUNT(*) FROM {quote_identifier(candidates[table])}
            WHERE {quote_identifier(concept_column)} <> 0
        """).fetchone()[0]
        for table, (_, concept_column) in SEMANTIC_CONCEPT_FIELDS.items()
    )
    provenance_exists = con.execute("""
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'main' AND table_name = 'mapping_provenance'
    """).fetchone()[0]
    if not provenance_exists:
        if mapped_count:
            raise ValueError(
                "Mapped clinical concepts exist without mapping_provenance."
            )
        return

    target_placeholders = ", ".join(
        "?" for _ in SEMANTIC_CONCEPT_FIELDS
    )
    foreign_runs = con.execute(f"""
        SELECT COUNT(*) FROM mapping_provenance
        WHERE target_table IN ({target_placeholders})
          AND (run_id IS NULL OR run_id <> ?)
    """, [*SEMANTIC_CONCEPT_FIELDS, expected_run_id]).fetchone()[0]
    if foreign_runs:
        raise ValueError(
            f"Mapping provenance contains {foreign_runs} row(s) outside "
            f"publication run {expected_run_id}."
        )

    for table, (id_column, concept_column) in SEMANTIC_CONCEPT_FIELDS.items():
        physical = candidates[table]
        missing_or_duplicate = con.execute(f"""
            SELECT COUNT(*)
            FROM {quote_identifier(physical)} t
            WHERE t.{quote_identifier(concept_column)} <> 0
              AND (
                  SELECT COUNT(*) FROM mapping_provenance p
                  WHERE p.run_id = ?
                    AND p.target_table = ?
                    AND p.target_id = t.{quote_identifier(id_column)}
                    AND p.assigned_concept_id = t.{quote_identifier(concept_column)}
              ) <> 1
        """, [expected_run_id, table]).fetchone()[0]
        if missing_or_duplicate:
            raise ValueError(
                f"Mapping provenance coverage failed for {table}: "
                f"{missing_or_duplicate} mapped row(s) lack exactly one "
                "matching audit record."
            )

        orphan_or_mismatch = con.execute(f"""
            SELECT COUNT(*)
            FROM mapping_provenance p
            LEFT JOIN {quote_identifier(physical)} t
              ON p.target_id = t.{quote_identifier(id_column)}
            WHERE p.run_id = ? AND p.target_table = ?
              AND (
                  t.{quote_identifier(id_column)} IS NULL
                  OR t.{quote_identifier(concept_column)} = 0
                  OR p.assigned_concept_id <> t.{quote_identifier(concept_column)}
              )
        """, [expected_run_id, table]).fetchone()[0]
        if orphan_or_mismatch:
            raise ValueError(
                f"Mapping provenance integrity failed for {table}: "
                f"{orphan_or_mismatch} orphan or mismatched audit row(s)."
            )


def _validate_candidates(con, candidates):
    care_site = candidates["care_site"]
    person = candidates["person"]
    visit = candidates["visit_occurrence"]
    _require_no_orphans(
        con, person, "care_site_id", care_site, "care_site_id", nullable=True
    )
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
    for table, event_date, max_window_days in (
        ("condition_occurrence", "condition_start_date", 0),
        ("drug_exposure", "drug_exposure_start_date", 0),
        # LB/VS/EG carry an explicit CDISC VISITNUM. The synthetic protocol
        # permits assessments around the nominal SV date, so that explicit
        # linkage wins within a reviewed seven-day visit window.
        ("measurement", "measurement_date", 7),
    ):
        _require_consistent_visit_link(
            con, candidates[table], event_date, visit, max_window_days
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


def _validate_lineage(con, lineage, candidates):
    unexpected = con.execute(f"""
        SELECT DISTINCT target_table
        FROM {quote_identifier(lineage)}
        WHERE target_table NOT IN ({", ".join("?" for _ in LINEAGE_TARGETS)})
    """, list(LINEAGE_TARGETS)).fetchall()
    if unexpected:
        raise ValueError(f"Unsupported lineage targets: {unexpected}")

    run_ids = con.execute(f"""
        SELECT DISTINCT run_id FROM {quote_identifier(lineage)}
    """).fetchall()
    if len(run_ids) != 1:
        raise ValueError("Lineage must contain exactly one publication run_id.")
    lineage_run_id = run_ids[0][0]

    for target_table, id_column in LINEAGE_TARGETS.items():
        physical = candidates[target_table]
        lineage_count = con.execute(f"""
            SELECT COUNT(*) FROM {quote_identifier(lineage)}
            WHERE target_table = ?
        """, [target_table]).fetchone()[0]
        target_count = con.execute(
            f"SELECT COUNT(*) FROM {quote_identifier(physical)}"
        ).fetchone()[0]
        if lineage_count != target_count:
            raise ValueError(
                f"Lineage coverage failed for {target_table}: "
                f"lineage={lineage_count}, target={target_count}."
            )

        target_person = id_column if target_table == "person" else "person_id"
        invalid = con.execute(f"""
            SELECT COUNT(*)
            FROM {quote_identifier(lineage)} l
            LEFT JOIN {quote_identifier(physical)} t
              ON l.target_id = t.{quote_identifier(id_column)}
            WHERE l.target_table = ?
              AND (
                  t.{quote_identifier(id_column)} IS NULL
                  OR l.person_id <> t.{quote_identifier(target_person)}
              )
        """, [target_table]).fetchone()[0]
        if invalid:
            raise ValueError(
                f"Lineage integrity failed for {target_table}: {invalid} rows."
            )

    file_mismatches = con.execute(f"""
        SELECT COUNT(*) FROM {quote_identifier(lineage)}
        WHERE source_file <> LOWER(source_domain) || '.sas7bdat'
    """).fetchone()[0]
    if file_mismatches:
        raise ValueError(
            f"Lineage contains {file_mismatches} inconsistent source filenames."
        )
    return lineage_run_id

def build_omop_database(db_path=DB_PATH, processed_dir=None, run_id=None):
    print("🗄️ STARTING OMOP CDM 5.4 DATABASE PUBLICATION")
    print("-" * 70)
    print(f"Connecting to DuckDB at: {db_path}")
    processed_dir = Path(processed_dir or PROCESSED_DIR)
    paths = {
        table: processed_dir / filename
        for table, filename in PUBLICATION_FILES.items()
    }
    lineage_path = processed_dir / LINEAGE_FILE
    paths["source_record_lineage"] = lineage_path
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
                if table == "source_record_lineage":
                    continue
                print(f"📦 Staging and validating {csv_path.name}...")
                candidate, count = _stage_into_candidate(con, table, csv_path)
                candidates[table] = candidate
                counts[table] = count

            print(f"📦 Staging and validating {lineage_path.name}...")
            lineage_candidate, lineage_count = _stage_lineage_candidate(
                con, lineage_path
            )

            _validate_candidates(con, candidates)
            lineage_run_id = _validate_lineage(
                con, lineage_candidate, candidates
            )
            expected_run_id = run_id or lineage_run_id
            if lineage_run_id != expected_run_id:
                raise ValueError(
                    "Lineage run_id does not match the publication run_id."
                )
            _validate_mapping_provenance(
                con, candidates, expected_run_id
            )

            con.execute("DROP TABLE IF EXISTS source_record_lineage")
            for table in reversed(PUBLICATION_FILES):
                con.execute(f"DROP TABLE IF EXISTS {quote_identifier(table)}")
            for table, candidate in candidates.items():
                con.execute(
                    f"ALTER TABLE {quote_identifier(candidate)} "
                    f"RENAME TO {quote_identifier(table)}"
                )
                validate_table_schema(con, table)
                print(f"   ✅ Published {counts[table]} records to {table}.")
            con.execute(
                f"ALTER TABLE {quote_identifier(lineage_candidate)} "
                "RENAME TO source_record_lineage"
            )
            print(
                f"   ✅ Published {lineage_count} records to "
                "source_record_lineage."
            )
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
        lineage_run_id = _validate_lineage(
            con, "source_record_lineage", candidates
        )
        _validate_mapping_provenance(con, candidates, lineage_run_id)
        counts = {
            table: con.execute(
                f"SELECT COUNT(*) FROM {quote_identifier(table)}"
            ).fetchone()[0]
            for table in PUBLICATION_FILES
        }
        lineage_count = con.execute(
            "SELECT COUNT(*) FROM source_record_lineage"
        ).fetchone()[0]
    return {
        "cdm_version": CDM_VERSION,
        "source_release": CDM_RELEASE,
        "schema_table_count": len(load_table_specs()),
        "row_counts": counts,
        "extension_counts": {
            "source_record_lineage": lineage_count
        },
    }

if __name__ == "__main__":
    build_omop_database(run_id=require_run_id())
