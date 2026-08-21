import re

from src.utils.run_context import ensure_audit_schema


PROMPT_VERSION = "candidate-selection-v1"
TARGET_DOMAINS = {
    "condition_occurrence": "Condition",
    "drug_exposure": "Drug",
    "measurement": "Measurement",
}


def normalize_source_value(value):
    """Return the stable key used by proposals and the approved mapping set."""
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


def get_vocabulary_version(con):
    try:
        row = con.execute(
            "SELECT vocabulary_version FROM cdm_source LIMIT 1"
        ).fetchone()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return "Athena_Standard"


def record_mapping_decision(
    con,
    *,
    run_id,
    target_table,
    source_value,
    proposed_concept_id,
    score,
    model_name,
    vocabulary_version,
    affected_target_ids,
    mapping_method="llm_zero_shot",
    prompt_version=PROMPT_VERSION,
):
    """Store an LLM proposal without applying it to a clinical table."""
    if target_table not in TARGET_DOMAINS:
        raise ValueError(f"Unsupported target table: {target_table}")

    ensure_audit_schema(con)
    normalized_value = normalize_source_value(source_value)
    proposed_concept_id = int(proposed_concept_id or 0)
    rejection = con.execute("""
        SELECT rejected_by, rejection_reason, rejected_at
        FROM rejected_mapping_set
        WHERE target_table = ? AND normalized_value = ? AND active = TRUE
    """, (target_table, normalized_value)).fetchone()
    if rejection:
        decision_status = "REJECTED_BY_POLICY"
        reviewed_by, review_reason, reviewed_at = rejection
    else:
        decision_status = "PROPOSED" if proposed_concept_id else "UNRESOLVED"
        reviewed_by = review_reason = reviewed_at = None

    con.execute("""
        INSERT INTO mapping_decision (
            run_id, target_table, source_value, normalized_value,
            proposed_concept_id, mapping_method, score, model_name,
            vocabulary_version, prompt_version, decision_status,
            reviewed_by, reviewed_at, review_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT DO NOTHING
    """, (
        run_id,
        target_table,
        str(source_value),
        normalized_value,
        proposed_concept_id,
        mapping_method,
        float(score),
        model_name,
        vocabulary_version,
        prompt_version,
        decision_status,
        reviewed_by,
        reviewed_at,
        review_reason,
    ))

    decision = con.execute("""
        SELECT mapping_decision_id, proposed_concept_id
        FROM mapping_decision
        WHERE run_id = ? AND target_table = ?
          AND normalized_value = ? AND mapping_method = ?
    """, (run_id, target_table, normalized_value, mapping_method)).fetchone()
    if decision is None:
        raise RuntimeError("The mapping decision could not be persisted.")
    if int(decision[1]) != proposed_concept_id:
        raise RuntimeError(
            "A different proposal already exists for this source value and run."
        )

    decision_id = int(decision[0])
    event_rows = [(decision_id, int(target_id)) for target_id in affected_target_ids]
    if event_rows:
        con.executemany("""
            INSERT INTO mapping_decision_event (mapping_decision_id, target_id)
            VALUES (?, ?)
            ON CONFLICT DO NOTHING
        """, event_rows)
    return decision_id


def import_pending_provenance(con, run_id):
    """Migrate pending event-level provenance into reviewable decisions."""
    ensure_audit_schema(con)
    groups = con.execute("""
        SELECT target_table, source_value, assigned_concept_id, score,
               model_name, vocabulary_version, mapping_method
        FROM mapping_provenance
        WHERE run_id = ? AND reviewed_by = 'Pending_Human_Review'
        GROUP BY ALL
        ORDER BY target_table, source_value
    """, [run_id]).fetchall()

    decision_ids = []
    for (
        target_table,
        source_value,
        concept_id,
        score,
        model_name,
        vocabulary_version,
        mapping_method,
    ) in groups:
        target_ids = [
            row[0]
            for row in con.execute("""
                SELECT target_id
                FROM mapping_provenance
                WHERE run_id = ? AND target_table = ? AND source_value = ?
                  AND assigned_concept_id = ? AND mapping_method = ?
                  AND reviewed_by = 'Pending_Human_Review'
                ORDER BY target_id
            """, (
                run_id,
                target_table,
                source_value,
                concept_id,
                mapping_method,
            )).fetchall()
        ]
        decision_ids.append(record_mapping_decision(
            con,
            run_id=run_id,
            target_table=target_table,
            source_value=source_value,
            proposed_concept_id=concept_id,
            score=score,
            model_name=model_name,
            vocabulary_version=vocabulary_version,
            affected_target_ids=target_ids,
            mapping_method=mapping_method,
            prompt_version="legacy-event-provenance-v1",
        ))
    return decision_ids


def review_decision(
    con,
    decision_id,
    *,
    action,
    reviewer,
    reason,
    selected_concept_id=None,
):
    """Approve or reject one proposal and maintain the approved mapping set."""
    action = action.upper()
    if action not in {"APPROVE", "REJECT"}:
        raise ValueError("Review action must be APPROVE or REJECT.")
    if not str(reviewer).strip() or not str(reason).strip():
        raise ValueError("Reviewer and reason are required.")

    ensure_audit_schema(con)
    decision = con.execute("""
        SELECT target_table, source_value, normalized_value,
               proposed_concept_id, decision_status
        FROM mapping_decision
        WHERE mapping_decision_id = ?
    """, [int(decision_id)]).fetchone()
    if decision is None:
        raise ValueError(f"Mapping decision {decision_id} does not exist.")
    if decision[4] in {"APPROVED", "REJECTED"}:
        raise ValueError(
            f"Mapping decision {decision_id} was already {decision[4]}."
        )

    target_table, source_value, normalized_value, proposed_id, _ = decision
    if action == "REJECT":
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute("""
                UPDATE mapping_decision
                SET decision_status = 'REJECTED', selected_concept_id = NULL,
                    reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP,
                    review_reason = ?
                WHERE mapping_decision_id = ?
            """, (reviewer, reason, int(decision_id)))
            con.execute("""
                UPDATE approved_mapping_set
                SET active = FALSE, updated_at = CURRENT_TIMESTAMP
                WHERE target_table = ? AND normalized_value = ?
            """, (target_table, normalized_value))
            con.execute("""
                INSERT INTO rejected_mapping_set (
                    target_table, source_value, normalized_value,
                    source_decision_id, rejected_by, rejection_reason,
                    rejected_at, active, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, TRUE, CURRENT_TIMESTAMP)
                ON CONFLICT (target_table, normalized_value) DO UPDATE SET
                    source_value = EXCLUDED.source_value,
                    source_decision_id = EXCLUDED.source_decision_id,
                    rejected_by = EXCLUDED.rejected_by,
                    rejection_reason = EXCLUDED.rejection_reason,
                    rejected_at = EXCLUDED.rejected_at,
                    active = TRUE,
                    updated_at = now()
            """, (
                target_table,
                source_value,
                normalized_value,
                int(decision_id),
                reviewer,
                reason,
            ))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        return {"decision_id": int(decision_id), "status": "REJECTED"}

    concept_id = int(selected_concept_id or proposed_id or 0)
    if concept_id == 0:
        raise ValueError("Approval requires a non-zero Standard Concept ID.")
    concept = con.execute("""
        SELECT concept_name, domain_id, standard_concept, invalid_reason
        FROM concept
        WHERE concept_id = ?
    """, [str(concept_id)]).fetchone()
    if concept is None:
        raise ValueError(f"Concept {concept_id} does not exist.")

    concept_name, domain_id, standard_concept, invalid_reason = concept
    expected_domain = TARGET_DOMAINS[target_table]
    if standard_concept != "S" or invalid_reason not in {None, ""}:
        raise ValueError(f"Concept {concept_id} is not a valid Standard Concept.")
    if domain_id != expected_domain:
        raise ValueError(
            f"Concept {concept_id} belongs to {domain_id}, but {target_table} "
            f"requires the {expected_domain} domain."
        )

    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("""
            UPDATE mapping_decision
            SET decision_status = 'APPROVED', selected_concept_id = ?,
                reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP,
                review_reason = ?
            WHERE mapping_decision_id = ?
        """, (concept_id, reviewer, reason, int(decision_id)))
        con.execute("""
            INSERT INTO approved_mapping_set (
                target_table, source_value, normalized_value, concept_id,
                source_decision_id, approved_by, approval_reason, approved_at,
                active, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, TRUE, CURRENT_TIMESTAMP)
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
            target_table,
            source_value,
            normalized_value,
            concept_id,
            int(decision_id),
            reviewer,
            reason,
        ))
        con.execute("""
            UPDATE rejected_mapping_set
            SET active = FALSE, updated_at = CURRENT_TIMESTAMP
            WHERE target_table = ? AND normalized_value = ?
        """, (target_table, normalized_value))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return {
        "decision_id": int(decision_id),
        "status": "APPROVED",
        "concept_id": concept_id,
        "concept_name": concept_name,
    }
