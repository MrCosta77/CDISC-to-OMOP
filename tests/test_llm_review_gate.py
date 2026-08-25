import duckdb
import pandas as pd
import pytest

from src.mapping.apply_approved_mappings import apply_approved_mappings
from src.mapping.review_mappings import create_manual_proposal, list_rules
from src.mapping.review_store import (
    get_active_mapping_rule,
    record_mapping_decision,
    review_decision,
)
from src.utils.run_context import ensure_audit_schema


def _create_concepts(con):
    con.execute("""
        CREATE TABLE concept (
            concept_id VARCHAR,
            concept_name VARCHAR,
            domain_id VARCHAR,
            standard_concept VARCHAR,
            invalid_reason VARCHAR,
            valid_start_date DATE,
            valid_end_date DATE
        )
    """)
    con.executemany("""
        INSERT INTO concept VALUES (
            ?, ?, ?, 'S', NULL, '1970-01-01', '2099-12-31'
        )
    """, [
        ("320128", "Essential hypertension", "Condition"),
        ("4223659", "Fatigue", "Observation"),
    ])


def test_proposal_is_not_provenance_and_wrong_domain_cannot_be_approved():
    with duckdb.connect(":memory:") as con:
        _create_concepts(con)
        ensure_audit_schema(con)
        decision_id = record_mapping_decision(
            con,
            run_id="RUN-REVIEW",
            target_table="condition_occurrence",
            source_value="Hypertension",
            proposed_concept_id=320128,
            score=0.75,
            model_name="test-model",
            vocabulary_version="test-vocab",
            affected_target_ids=[10, 11],
        )

        assert con.execute(
            "SELECT decision_status FROM mapping_decision"
        ).fetchone()[0] == "PROPOSED"
        assert con.execute(
            "SELECT COUNT(*) FROM mapping_decision_event"
        ).fetchone()[0] == 2
        assert con.execute(
            "SELECT COUNT(*) FROM mapping_provenance"
        ).fetchone()[0] == 0

        with pytest.raises(ValueError, match="requires the Condition domain"):
            review_decision(
                con,
                decision_id,
                action="approve",
                reviewer="QC Reviewer",
                reason="Wrong-domain test",
                selected_concept_id=4223659,
            )

        review_decision(
            con,
            decision_id,
            action="reject",
            reviewer="QC Reviewer",
            reason="Source does not support the proposed specificity",
        )
        policy_decision_id = record_mapping_decision(
            con,
            run_id="RUN-NEXT",
            target_table="condition_occurrence",
            source_value="Hypertension",
            proposed_concept_id=320128,
            score=0.75,
            model_name="test-model",
            vocabulary_version="test-vocab",
            affected_target_ids=[12],
        )
        policy_status = con.execute("""
            SELECT decision_status, reviewed_by
            FROM mapping_decision
            WHERE mapping_decision_id = ?
        """, [policy_decision_id]).fetchone()
        assert policy_status == ("REJECTED_BY_POLICY", "QC Reviewer")

        review_decision(
            con,
            policy_decision_id,
            action="approve",
            reviewer="Senior Reviewer",
            reason="Reconsidered with a valid generic Standard Concept",
        )
        assert con.execute("""
            SELECT active FROM rejected_mapping_set
            WHERE target_table = 'condition_occurrence'
              AND normalized_value = 'hypertension'
        """).fetchone()[0] is False


def test_expired_standard_concept_cannot_be_approved():
    with duckdb.connect(":memory:") as con:
        _create_concepts(con)
        ensure_audit_schema(con)
        con.execute(
            "UPDATE concept SET valid_end_date = '2000-12-31' "
            "WHERE concept_id = '320128'"
        )
        decision_id = record_mapping_decision(
            con,
            run_id="RUN-EXPIRED",
            target_table="condition_occurrence",
            source_value="Hypertension",
            proposed_concept_id=320128,
            score=1.0,
            model_name="test-model",
            vocabulary_version="test-vocab",
            affected_target_ids=[1],
        )
        with pytest.raises(ValueError, match="not currently valid"):
            review_decision(
                con,
                decision_id,
                action="approve",
                reviewer="QC Reviewer",
                reason="Expired concept regression test",
            )


def test_only_approved_mapping_is_applied_and_audited(tmp_path):
    db_path = tmp_path / "review.duckdb"
    with duckdb.connect(str(db_path)) as con:
        _create_concepts(con)
        ensure_audit_schema(con)
        decision_id = record_mapping_decision(
            con,
            run_id="RUN-PROPOSAL",
            target_table="condition_occurrence",
            source_value="Hypertension",
            proposed_concept_id=320128,
            score=0.75,
            model_name="test-model",
            vocabulary_version="test-vocab",
            affected_target_ids=[1],
        )
        result = review_decision(
            con,
            decision_id,
            action="approve",
            reviewer="QC Reviewer",
            reason="Validated against the local Standard Vocabulary",
        )
        assert result["status"] == "APPROVED"

    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    pd.DataFrame({
        "condition_occurrence_id": [1, 2],
        "condition_source_value": ["Hypertension", "Fatigue"],
        "condition_concept_id": [0, 0],
    }).to_csv(processed_dir / "CONDITION_OCCURRENCE.csv", index=False)
    pd.DataFrame({
        "drug_exposure_id": [1],
        "drug_source_value": ["Active Drug"],
        "drug_concept_id": [0],
    }).to_csv(processed_dir / "DRUG_EXPOSURE.csv", index=False)
    pd.DataFrame({
        "measurement_id": [1],
        "measurement_source_value": ["RR Duration"],
        "measurement_concept_id": [0],
    }).to_csv(processed_dir / "MEASUREMENT.csv", index=False)

    assert apply_approved_mappings(
        db_path=db_path,
        processed_dir=processed_dir,
        run_id="RUN-APPLY",
    ) == 1
    assert apply_approved_mappings(
        db_path=db_path,
        processed_dir=processed_dir,
        run_id="RUN-APPLY",
    ) == 0

    condition = pd.read_csv(processed_dir / "CONDITION_OCCURRENCE.csv")
    assert condition["condition_concept_id"].tolist() == [320128, 0]
    with duckdb.connect(str(db_path), read_only=True) as con:
        provenance = con.execute("""
            SELECT assigned_concept_id, reviewed_by, run_id,
                   mapping_decision_id, COUNT(*)
            FROM mapping_provenance
            GROUP BY ALL
        """).fetchone()
    assert provenance == (320128, "QC Reviewer", "RUN-APPLY", decision_id, 1)


def test_active_review_rules_can_be_listed(capsys):
    with duckdb.connect(":memory:") as con:
        _create_concepts(con)
        ensure_audit_schema(con)
        approved_id = record_mapping_decision(
            con,
            run_id="RUN-RULES",
            target_table="condition_occurrence",
            source_value="Hypertension",
            proposed_concept_id=320128,
            score=0.75,
            model_name="test-model",
            vocabulary_version="test-vocab",
            affected_target_ids=[1],
        )
        review_decision(
            con,
            approved_id,
            action="approve",
            reviewer="QC Reviewer",
            reason="Approved rule",
        )
        rejected_id = record_mapping_decision(
            con,
            run_id="RUN-RULES",
            target_table="condition_occurrence",
            source_value="Fatigue",
            proposed_concept_id=320128,
            score=0.50,
            model_name="test-model",
            vocabulary_version="test-vocab",
            affected_target_ids=[2],
        )
        review_decision(
            con,
            rejected_id,
            action="reject",
            reviewer="QC Reviewer",
            reason="Rejected rule",
        )

        approved, rejected = list_rules(con)

    output = capsys.readouterr().out
    assert len(approved) == 1
    assert len(rejected) == 1
    assert "Hypertension -> 320128 (Essential hypertension)" in output
    assert "Fatigue" in output


def test_threshold_and_active_rejection_are_machine_readable():
    with duckdb.connect(":memory:") as con:
        _create_concepts(con)
        ensure_audit_schema(con)
        decision_id = record_mapping_decision(
            con,
            run_id="RUN-LOW",
            target_table="condition_occurrence",
            source_value="Ambiguous term",
            proposed_concept_id=320128,
            score=0.45,
            minimum_score=0.90,
            model_name="test-model",
            vocabulary_version="test-vocab",
            affected_target_ids=[1],
        )
        assert con.execute(
            "SELECT decision_status FROM mapping_decision WHERE mapping_decision_id = ?",
            [decision_id],
        ).fetchone()[0] == "LOW_CONFIDENCE"

        review_decision(
            con,
            decision_id,
            action="reject",
            reviewer="QC Reviewer",
            reason="Below the calibrated threshold",
        )
        status, rule = get_active_mapping_rule(
            con, "condition_occurrence", "  AMBIGUOUS   TERM "
        )

    assert status == "REJECTED"
    assert rule[0] == "QC Reviewer"


def test_manual_review_resolves_events_through_published_lineage():
    with duckdb.connect(":memory:") as con:
        _create_concepts(con)
        ensure_audit_schema(con)
        con.execute("""
            CREATE TABLE source_record_lineage (
                target_table VARCHAR,
                target_id BIGINT,
                mapping_source_value VARCHAR
            )
        """)
        con.executemany(
            "INSERT INTO source_record_lineage VALUES (?, ?, ?)",
            [
                ("condition_occurrence", 41, "Hypertension"),
                ("condition_occurrence", 42, "Hypertension"),
            ],
        )

        decision_id = create_manual_proposal(
            con,
            "RUN-LINEAGE-REVIEW",
            "condition_occurrence",
            "Hypertension",
            320128,
        )
        targets = con.execute("""
            SELECT target_id FROM mapping_decision_event
            WHERE mapping_decision_id = ? ORDER BY target_id
        """, [decision_id]).fetchall()

    assert targets == [(41,), (42,)]
