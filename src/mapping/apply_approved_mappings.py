import sys
from pathlib import Path

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.mapping.review_store import normalize_source_value
from src.utils.config import DB_PATH
from src.utils.run_context import ensure_audit_schema, require_run_id


MAPPING_TARGETS = {
    "condition_occurrence": {
        "filename": "CONDITION_OCCURRENCE.csv",
        "id_column": "condition_occurrence_id",
        "source_column": "condition_source_value",
        "concept_column": "condition_concept_id",
        "domain": "Condition",
    },
    "drug_exposure": {
        "filename": "DRUG_EXPOSURE.csv",
        "id_column": "drug_exposure_id",
        "source_column": "drug_source_value",
        "concept_column": "drug_concept_id",
        "domain": "Drug",
    },
    "measurement": {
        "filename": "MEASUREMENT.csv",
        "id_column": "measurement_id",
        "source_column": "measurement_source_value",
        "concept_column": "measurement_concept_id",
        "domain": "Measurement",
    },
}


def _load_active_approvals(con, target_table, expected_domain):
    rows = con.execute("""
        SELECT a.normalized_value, a.concept_id, a.source_decision_id,
               a.approved_by, d.score, d.model_name, d.vocabulary_version,
               c.concept_name, c.domain_id, c.standard_concept, c.invalid_reason
        FROM approved_mapping_set a
        JOIN mapping_decision d
          ON d.mapping_decision_id = a.source_decision_id
        LEFT JOIN concept c
          ON CAST(c.concept_id AS BIGINT) = a.concept_id
        WHERE a.target_table = ? AND a.active = TRUE
        ORDER BY a.normalized_value
    """, [target_table]).fetchall()

    approvals = {}
    for row in rows:
        (
            normalized_value,
            concept_id,
            decision_id,
            approved_by,
            score,
            model_name,
            vocabulary_version,
            concept_name,
            domain_id,
            standard_concept,
            invalid_reason,
        ) = row
        if concept_name is None:
            raise ValueError(f"Approved concept {concept_id} no longer exists.")
        if standard_concept != "S" or invalid_reason not in {None, ""}:
            raise ValueError(
                f"Approved concept {concept_id} is no longer a valid Standard Concept."
            )
        if domain_id != expected_domain:
            raise ValueError(
                f"Approved concept {concept_id} belongs to {domain_id}; "
                f"{target_table} requires {expected_domain}."
            )
        approvals[normalized_value] = {
            "concept_id": int(concept_id),
            "decision_id": int(decision_id),
            "approved_by": approved_by,
            "score": float(score),
            "model_name": model_name,
            "vocabulary_version": vocabulary_version,
        }
    return approvals


def _apply_target(df, target_table, config, approvals, con, run_id):
    if not approvals:
        return df, 0

    concept_column = config["concept_column"]
    source_column = config["source_column"]
    id_column = config["id_column"]

    df = df.copy()
    df[concept_column] = pd.to_numeric(
        df[concept_column], errors="coerce"
    ).fillna(0).astype("Int64")
    normalized = df[source_column].map(normalize_source_value)
    mask = (df[concept_column] == 0) & normalized.isin(approvals)

    audit_records = []
    for index in df.index[mask]:
        approval = approvals[normalized.loc[index]]
        df.loc[index, concept_column] = approval["concept_id"]
        audit_records.append((
            target_table,
            int(df.loc[index, id_column]),
            str(df.loc[index, source_column]),
            normalized.loc[index],
            approval["concept_id"],
            "human_approved_mapping",
            approval["score"],
            approval["model_name"],
            approval["vocabulary_version"],
            approval["approved_by"],
            run_id,
            approval["decision_id"],
        ))

    if audit_records:
        con.executemany("""
            INSERT INTO mapping_provenance (
                target_table, target_id, source_value, normalized_value,
                assigned_concept_id, mapping_method, score, model_name,
                vocabulary_version, reviewed_by, run_id, mapping_decision_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT DO NOTHING
        """, audit_records)
    return df, len(audit_records)


def apply_approved_mappings(db_path=DB_PATH, processed_dir=None, run_id=None):
    run_id = run_id or require_run_id()
    processed_dir = Path(processed_dir or PROJECT_ROOT / "data" / "processed")
    missing = [
        str(processed_dir / config["filename"])
        for config in MAPPING_TARGETS.values()
        if not (processed_dir / config["filename"]).is_file()
    ]
    if missing:
        raise FileNotFoundError(
            "Approved mappings require all processed mapping inputs:\n- "
            + "\n- ".join(missing)
        )

    total = 0
    with duckdb.connect(str(db_path)) as con:
        ensure_audit_schema(con)
        for target_table, config in MAPPING_TARGETS.items():
            csv_path = processed_dir / config["filename"]
            df = pd.read_csv(csv_path)
            approvals = _load_active_approvals(
                con, target_table, config["domain"]
            )
            df, applied = _apply_target(
                df, target_table, config, approvals, con, run_id
            )
            if applied:
                df.to_csv(csv_path, index=False)
            total += applied
            print(
                f"[{target_table}] Applied {applied} human-approved mappings."
            )
    print(f"✅ Applied {total} approved mappings across all clinical domains.")
    return total


if __name__ == "__main__":
    apply_approved_mappings()
