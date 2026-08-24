"""Deterministic export and import of reviewed human mapping rules."""

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from src.mapping.review_store import TARGET_DOMAINS, normalize_source_value
from src.utils.run_context import ensure_audit_schema
from src.utils.vocabulary_identity import load_vocabulary_manifest


RULESET_SCHEMA_VERSION = 1


def _timestamp(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _ruleset_fingerprint(payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def export_mapping_rules(con, output_path, vocabulary_manifest_path):
    """Export active approvals and rejections without clinical event data."""
    ensure_audit_schema(con)
    vocabulary = load_vocabulary_manifest(vocabulary_manifest_path)
    approved = [
        {
            "target_table": row[0],
            "source_value": row[1],
            "normalized_value": row[2],
            "concept_id": int(row[3]),
            "reviewed_by": row[4],
            "review_reason": row[5],
            "reviewed_at": _timestamp(row[6]),
        }
        for row in con.execute("""
            SELECT target_table, source_value, normalized_value, concept_id,
                   approved_by, approval_reason, approved_at
            FROM approved_mapping_set
            WHERE active
            ORDER BY target_table, normalized_value
        """).fetchall()
    ]
    rejected = [
        {
            "target_table": row[0],
            "source_value": row[1],
            "normalized_value": row[2],
            "reviewed_by": row[3],
            "review_reason": row[4],
            "reviewed_at": _timestamp(row[5]),
        }
        for row in con.execute("""
            SELECT target_table, source_value, normalized_value,
                   rejected_by, rejection_reason, rejected_at
            FROM rejected_mapping_set
            WHERE active
            ORDER BY target_table, normalized_value
        """).fetchall()
    ]
    core = {
        "schema_version": RULESET_SCHEMA_VERSION,
        "vocabulary_fingerprint": vocabulary["fingerprint"],
        "vocabulary_version": vocabulary["version_label"],
        "approved": approved,
        "rejected": rejected,
    }
    payload = dict(core)
    payload["ruleset_fingerprint"] = _ruleset_fingerprint(core)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def load_mapping_rules(rules_path):
    rules_path = Path(rules_path)
    if not rules_path.is_file():
        raise FileNotFoundError(f"Versioned mapping rules are missing: {rules_path}")
    payload = json.loads(rules_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != RULESET_SCHEMA_VERSION:
        raise ValueError("Unsupported mapping rules schema.")
    core = {
        key: payload.get(key)
        for key in (
            "schema_version",
            "vocabulary_fingerprint",
            "vocabulary_version",
            "approved",
            "rejected",
        )
    }
    if payload.get("ruleset_fingerprint") != _ruleset_fingerprint(core):
        raise ValueError("Mapping rules fingerprint is invalid.")
    return payload


def _validate_rule(rule, *, approved):
    target_table = rule.get("target_table")
    if target_table not in TARGET_DOMAINS:
        raise ValueError(f"Unsupported mapping target in ruleset: {target_table}")
    source_value = str(rule.get("source_value") or "").strip()
    if not source_value:
        raise ValueError("Mapping rule source_value is required.")
    if rule.get("normalized_value") != normalize_source_value(source_value):
        raise ValueError(f"Mapping rule normalization mismatch: {source_value}")
    for field in ("reviewed_by", "review_reason", "reviewed_at"):
        if not str(rule.get(field) or "").strip():
            raise ValueError(f"Mapping rule {field} is required: {source_value}")
    if approved and int(rule.get("concept_id") or 0) == 0:
        raise ValueError(f"Approved rule requires a concept ID: {source_value}")


def _validate_concept(con, target_table, concept_id):
    concept = con.execute("""
        SELECT domain_id, standard_concept, invalid_reason
        FROM concept WHERE concept_id = ?
    """, [str(concept_id)]).fetchone()
    if concept is None:
        raise ValueError(f"Ruleset concept {concept_id} does not exist.")
    domain_id, standard_concept, invalid_reason = concept
    if standard_concept != "S" or invalid_reason not in {None, ""}:
        raise ValueError(f"Ruleset concept {concept_id} is not a valid Standard Concept.")
    if domain_id != TARGET_DOMAINS[target_table]:
        raise ValueError(
            f"Ruleset concept {concept_id} belongs to {domain_id}, but "
            f"{target_table} requires {TARGET_DOMAINS[target_table]}."
        )


def _portable_decision_id(con, ruleset_run_id, rule, status, vocabulary_version):
    mapping_method = "versioned_human_rule"
    existing = con.execute("""
        SELECT mapping_decision_id
        FROM mapping_decision
        WHERE run_id = ? AND target_table = ? AND normalized_value = ?
          AND mapping_method = ?
    """, (
        ruleset_run_id,
        rule["target_table"],
        rule["normalized_value"],
        mapping_method,
    )).fetchone()
    if existing:
        return int(existing[0])

    concept_id = int(rule.get("concept_id") or 0)
    return int(con.execute("""
        INSERT INTO mapping_decision (
            run_id, target_table, source_value, normalized_value,
            proposed_concept_id, selected_concept_id, mapping_method, score,
            model_name, vocabulary_version, prompt_version, decision_status,
            reviewed_by, reviewed_at, review_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1.0, ?, ?, ?, ?, ?, ?, ?)
        RETURNING mapping_decision_id
    """, (
        ruleset_run_id,
        rule["target_table"],
        rule["source_value"],
        rule["normalized_value"],
        concept_id,
        concept_id if status == "APPROVED" else None,
        mapping_method,
        "Versioned_Human_Review",
        vocabulary_version,
        "portable-mapping-rules-v1",
        status,
        rule["reviewed_by"],
        rule["reviewed_at"],
        rule["review_reason"],
    )).fetchone()[0])


def import_mapping_rules(con, rules_path, vocabulary_manifest_path):
    """Merge the versioned rules into a new or existing audit database."""
    ensure_audit_schema(con)
    payload = load_mapping_rules(rules_path)
    vocabulary = load_vocabulary_manifest(vocabulary_manifest_path)
    if payload["vocabulary_fingerprint"] != vocabulary["fingerprint"]:
        raise ValueError(
            "Mapping rules were reviewed against a different Athena vocabulary."
        )
    if payload["vocabulary_version"] != vocabulary["version_label"]:
        raise ValueError("Mapping rules vocabulary label does not match the manifest.")

    for rule in payload["approved"]:
        _validate_rule(rule, approved=True)
        _validate_concept(con, rule["target_table"], int(rule["concept_id"]))
    for rule in payload["rejected"]:
        _validate_rule(rule, approved=False)

    ruleset_run_id = f"RULESET-{payload['ruleset_fingerprint'][:16]}"
    con.execute("BEGIN TRANSACTION")
    try:
        for rule in payload["approved"]:
            decision_id = _portable_decision_id(
                con, ruleset_run_id, rule, "APPROVED", payload["vocabulary_version"]
            )
            con.execute("""
                INSERT INTO approved_mapping_set (
                    target_table, source_value, normalized_value, concept_id,
                    source_decision_id, approved_by, approval_reason, approved_at,
                    active, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, TRUE, CURRENT_TIMESTAMP)
                ON CONFLICT (target_table, normalized_value) DO UPDATE SET
                    source_value = EXCLUDED.source_value,
                    concept_id = EXCLUDED.concept_id,
                    source_decision_id = EXCLUDED.source_decision_id,
                    approved_by = EXCLUDED.approved_by,
                    approval_reason = EXCLUDED.approval_reason,
                    approved_at = EXCLUDED.approved_at,
                    active = TRUE,
                    updated_at = now()
            """, (
                rule["target_table"], rule["source_value"],
                rule["normalized_value"], int(rule["concept_id"]), decision_id,
                rule["reviewed_by"], rule["review_reason"], rule["reviewed_at"],
            ))
            con.execute("""
                UPDATE rejected_mapping_set SET active = FALSE,
                    updated_at = now()
                WHERE target_table = ? AND normalized_value = ?
            """, (rule["target_table"], rule["normalized_value"]))

        for rule in payload["rejected"]:
            decision_id = _portable_decision_id(
                con, ruleset_run_id, rule, "REJECTED", payload["vocabulary_version"]
            )
            con.execute("""
                INSERT INTO rejected_mapping_set (
                    target_table, source_value, normalized_value,
                    source_decision_id, rejected_by, rejection_reason,
                    rejected_at, active, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, TRUE, CURRENT_TIMESTAMP)
                ON CONFLICT (target_table, normalized_value) DO UPDATE SET
                    source_value = EXCLUDED.source_value,
                    source_decision_id = EXCLUDED.source_decision_id,
                    rejected_by = EXCLUDED.rejected_by,
                    rejection_reason = EXCLUDED.rejection_reason,
                    rejected_at = EXCLUDED.rejected_at,
                    active = TRUE,
                    updated_at = now()
            """, (
                rule["target_table"], rule["source_value"],
                rule["normalized_value"], decision_id, rule["reviewed_by"],
                rule["review_reason"], rule["reviewed_at"],
            ))
            con.execute("""
                UPDATE approved_mapping_set SET active = FALSE,
                    updated_at = now()
                WHERE target_table = ? AND normalized_value = ?
            """, (rule["target_table"], rule["normalized_value"]))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return {
        "approved": len(payload["approved"]),
        "rejected": len(payload["rejected"]),
        "ruleset_fingerprint": payload["ruleset_fingerprint"],
    }
