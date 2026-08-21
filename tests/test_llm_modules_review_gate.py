from pathlib import Path

import duckdb
import pandas as pd
import pytest

from src.mapping import llm_condition, llm_drug, llm_measurement


@pytest.mark.parametrize(
    (
        "module",
        "runner_name",
        "filename",
        "id_column",
        "source_column",
        "concept_column",
        "target_table",
    ),
    [
        (
            llm_condition,
            "run_llm_condition_mapping",
            "CONDITION_OCCURRENCE.csv",
            "condition_occurrence_id",
            "condition_source_value",
            "condition_concept_id",
            "condition_occurrence",
        ),
        (
            llm_drug,
            "run_llm_drug_mapping",
            "DRUG_EXPOSURE.csv",
            "drug_exposure_id",
            "drug_source_value",
            "drug_concept_id",
            "drug_exposure",
        ),
        (
            llm_measurement,
            "run_llm_measurement_mapping",
            "MEASUREMENT.csv",
            "measurement_id",
            "measurement_source_value",
            "measurement_concept_id",
            "measurement",
        ),
    ],
)
def test_llm_module_records_proposal_without_updating_csv(
    monkeypatch,
    tmp_path,
    module,
    runner_name,
    filename,
    id_column,
    source_column,
    concept_column,
    target_table,
):
    processed_dir = tmp_path / "data" / "processed"
    processed_dir.mkdir(parents=True)
    csv_path = processed_dir / filename
    pd.DataFrame({
        id_column: [7],
        source_column: ["Source term"],
        concept_column: [0],
    }).to_csv(csv_path, index=False)

    db_path = tmp_path / "review-gate.duckdb"
    monkeypatch.setenv("PIPELINE_RUN_ID", "RUN-GATE")
    monkeypatch.setattr(module, "PROJECT_ROOT", Path(tmp_path))
    monkeypatch.setattr(module, "DB_PATH", str(db_path))
    monkeypatch.setattr(
        module,
        "get_candidates_from_db_safe",
        lambda *_args, **_kwargs: [(123, "Candidate concept")],
    )
    monkeypatch.setattr(module, "ask_llm_to_pick", lambda *_args: 123)

    getattr(module, runner_name)()

    result = pd.read_csv(csv_path)
    assert result.loc[0, concept_column] == 0
    with duckdb.connect(str(db_path), read_only=True) as con:
        decision = con.execute("""
            SELECT target_table, proposed_concept_id, decision_status
            FROM mapping_decision
        """).fetchone()
        provenance_count = con.execute(
            "SELECT COUNT(*) FROM mapping_provenance"
        ).fetchone()[0]
    assert decision == (target_table, 123, "PROPOSED")
    assert provenance_count == 0
