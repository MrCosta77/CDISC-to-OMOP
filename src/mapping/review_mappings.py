import argparse
import sys
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.mapping.review_store import (
    get_vocabulary_version,
    import_pending_provenance,
    record_mapping_decision,
    review_decision,
)
from src.utils.config import DB_PATH
from src.utils.run_context import ensure_audit_schema


TARGET_COLUMNS = {
    "condition_occurrence": (
        "condition_occurrence_id",
        "condition_source_value",
    ),
    "drug_exposure": ("drug_exposure_id", "drug_source_value"),
    "measurement": ("measurement_id", "measurement_source_value"),
}


def _resolve_run_id(con, run_id):
    if run_id and run_id.lower() != "latest":
        return run_id
    row = con.execute("""
        SELECT run_id
        FROM pipeline_run
        ORDER BY started_at DESC
        LIMIT 1
    """).fetchone()
    if row is None:
        raise ValueError("No pipeline run is available for review.")
    return row[0]


def list_decisions(con, run_id):
    run_id = _resolve_run_id(con, run_id)
    rows = con.execute("""
        SELECT d.mapping_decision_id, d.target_table, d.source_value,
               d.proposed_concept_id, proposed.concept_name,
               d.selected_concept_id, selected.concept_name,
               d.score, d.decision_status, d.reviewed_by,
               COUNT(e.target_id) AS affected_events
        FROM mapping_decision d
        LEFT JOIN concept proposed
          ON proposed.concept_id = CAST(d.proposed_concept_id AS VARCHAR)
        LEFT JOIN concept selected
          ON selected.concept_id = CAST(d.selected_concept_id AS VARCHAR)
        LEFT JOIN mapping_decision_event e
          ON e.mapping_decision_id = d.mapping_decision_id
        WHERE d.run_id = ?
        GROUP BY ALL
        ORDER BY d.target_table, d.source_value
    """, [run_id]).fetchall()

    print(f"Mapping decisions for {run_id}")
    if not rows:
        print("No decisions found.")
        return rows
    for row in rows:
        (
            decision_id,
            target_table,
            source_value,
            proposed_id,
            proposed_name,
            selected_id,
            selected_name,
            score,
            status,
            reviewed_by,
            affected_events,
        ) = row
        proposed = (
            f"{proposed_id} ({proposed_name})" if proposed_id else "no match"
        )
        selected = (
            f" -> {selected_id} ({selected_name})" if selected_id else ""
        )
        reviewer = f" by {reviewed_by}" if reviewed_by else ""
        print(
            f"[{decision_id}] {target_table} | {source_value} | "
            f"{proposed}{selected} | score={score:.2f} | {status}{reviewer} | "
            f"events={affected_events}"
        )
    return rows


def list_rules(con):
    approved = con.execute("""
        SELECT a.target_table, a.source_value, a.concept_id,
               c.concept_name, a.approved_by, a.approved_at,
               a.source_decision_id
        FROM approved_mapping_set a
        LEFT JOIN concept c ON c.concept_id = CAST(a.concept_id AS VARCHAR)
        WHERE a.active
        ORDER BY a.target_table, a.source_value
    """).fetchall()
    rejected = con.execute("""
        SELECT target_table, source_value, rejected_by, rejected_at,
               source_decision_id
        FROM rejected_mapping_set
        WHERE active
        ORDER BY target_table, source_value
    """).fetchall()

    print("Active approved mapping rules")
    if not approved:
        print("No active approved rules.")
    for (
        table,
        source,
        concept_id,
        concept_name,
        reviewer,
        reviewed_at,
        decision_id,
    ) in approved:
        print(
            f"[{decision_id}] {table} | {source} -> "
            f"{concept_id} ({concept_name}) | approved by {reviewer} at {reviewed_at}"
        )

    print("\nActive rejected mapping rules")
    if not rejected:
        print("No active rejected rules.")
    for table, source, reviewer, reviewed_at, decision_id in rejected:
        print(
            f"[{decision_id}] {table} | {source} | "
            f"rejected by {reviewer} at {reviewed_at}"
        )
    return approved, rejected


def create_manual_proposal(con, run_id, target_table, source_value, concept_id):
    run_id = _resolve_run_id(con, run_id)
    id_column, source_column = TARGET_COLUMNS[target_table]
    target_ids = [
        row[0]
        for row in con.execute(
            f'SELECT "{id_column}" FROM "{target_table}" '
            f'WHERE "{source_column}" = ? ORDER BY "{id_column}"',
            [source_value],
        ).fetchall()
    ]
    if not target_ids:
        raise ValueError(
            f"No {target_table} events were found for source value {source_value!r}."
        )
    return record_mapping_decision(
        con,
        run_id=run_id,
        target_table=target_table,
        source_value=source_value,
        proposed_concept_id=concept_id,
        score=1.0 if concept_id else 0.0,
        model_name="Human_Vocabulary_Review",
        vocabulary_version=get_vocabulary_version(con),
        affected_target_ids=target_ids,
        mapping_method="manual_vocabulary_review",
        prompt_version="human-vocabulary-review-v1",
    )


def build_parser():
    parser = argparse.ArgumentParser(
        description="Review LLM mapping proposals before they enter the OMOP CDM."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List mapping decisions.")
    list_parser.add_argument("--run-id", default="latest")

    subparsers.add_parser(
        "rules", help="List the active approved and rejected mapping rules."
    )

    import_parser = subparsers.add_parser(
        "import-pending", help="Import legacy pending provenance for review."
    )
    import_parser.add_argument("--run-id", required=True)

    propose_parser = subparsers.add_parser(
        "propose", help="Create a manual vocabulary proposal for a source value."
    )
    propose_parser.add_argument("--run-id", default="latest")
    propose_parser.add_argument(
        "--target-table", required=True, choices=sorted(TARGET_COLUMNS)
    )
    propose_parser.add_argument("--source-value", required=True)
    propose_parser.add_argument("--concept-id", type=int, default=0)

    approve_parser = subparsers.add_parser("approve", help="Approve a decision.")
    approve_parser.add_argument("decision_id", type=int)
    approve_parser.add_argument("--reviewer", required=True)
    approve_parser.add_argument("--reason", required=True)
    approve_parser.add_argument("--concept-id", type=int)

    reject_parser = subparsers.add_parser("reject", help="Reject a decision.")
    reject_parser.add_argument("decision_id", type=int)
    reject_parser.add_argument("--reviewer", required=True)
    reject_parser.add_argument("--reason", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    with duckdb.connect(DB_PATH) as con:
        ensure_audit_schema(con)
        if args.command == "list":
            list_decisions(con, args.run_id)
            return
        if args.command == "rules":
            list_rules(con)
            return
        if args.command == "import-pending":
            decision_ids = import_pending_provenance(con, args.run_id)
            print(
                f"Imported/verified {len(decision_ids)} pending decisions "
                f"for {args.run_id}."
            )
            list_decisions(con, args.run_id)
            return
        if args.command == "propose":
            decision_id = create_manual_proposal(
                con,
                args.run_id,
                args.target_table,
                args.source_value,
                args.concept_id,
            )
            print(f"Created/verified manual decision {decision_id}.")
            return

        result = review_decision(
            con,
            args.decision_id,
            action=args.command,
            reviewer=args.reviewer,
            reason=args.reason,
            selected_concept_id=getattr(args, "concept_id", None),
        )
        print(result)


if __name__ == "__main__":
    main()
