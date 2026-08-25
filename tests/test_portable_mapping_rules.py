import json
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from src.mapping.review_store import record_mapping_decision, review_decision
from src.mapping.rule_portability import (
    export_mapping_rules,
    import_mapping_rules,
)
from src.utils.run_context import ensure_audit_schema
from src.utils.vocabulary_identity import (
    VOCABULARY_FILES,
    validate_vocabulary_manifest,
    write_vocabulary_manifest,
)


def _write_fake_vocabulary(directory, suffix="A"):
    directory.mkdir()
    for name in VOCABULARY_FILES:
        content = f"field\n{name}-{suffix}\n"
        if name == "VOCABULARY.csv":
            content = (
                "vocabulary_id\tvocabulary_name\tvocabulary_reference\t"
                "vocabulary_version\tvocabulary_concept_id\n"
                f"RxNorm\tRxNorm\tNLM\tRxNorm-{suffix}\t1\n"
            )
        (directory / name).write_text(content, encoding="utf-8")


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
    con.execute(
        "INSERT INTO concept VALUES ('1125315', 'Acetaminophen', 'Drug', 'S', "
        "NULL, '1970-01-01', '2099-12-31')"
    )


def test_vocabulary_manifest_detects_changed_extract(tmp_path):
    vocab_dir = tmp_path / "vocab"
    manifest_path = tmp_path / "manifest.json"
    _write_fake_vocabulary(vocab_dir)
    manifest = write_vocabulary_manifest(vocab_dir, manifest_path)

    assert manifest["version_label"].startswith("Athena-")
    assert validate_vocabulary_manifest(vocab_dir, manifest_path) == manifest

    concept_path = vocab_dir / "CONCEPT.csv"
    concept_path.write_text("changed-content", encoding="utf-8")
    with pytest.raises(ValueError, match="size mismatch|checksum mismatch"):
        validate_vocabulary_manifest(vocab_dir, manifest_path)


def test_reviewed_rules_round_trip_into_clean_database(tmp_path):
    vocab_dir = tmp_path / "vocab"
    manifest_path = tmp_path / "manifest.json"
    rules_path = tmp_path / "mapping_rules.json"
    _write_fake_vocabulary(vocab_dir)
    manifest = write_vocabulary_manifest(vocab_dir, manifest_path)

    with duckdb.connect(":memory:") as source:
        _create_concepts(source)
        ensure_audit_schema(source)
        approved_id = record_mapping_decision(
            source,
            run_id="RUN-REVIEW",
            target_table="drug_exposure",
            source_value="Paracetamol",
            proposed_concept_id=1125315,
            score=1.0,
            model_name="test-model",
            vocabulary_version=manifest["version_label"],
            affected_target_ids=[1],
        )
        review_decision(
            source,
            approved_id,
            action="approve",
            reviewer="Mario Costa",
            reason="Validated against RxNorm",
        )
        rejected_id = record_mapping_decision(
            source,
            run_id="RUN-REVIEW",
            target_table="drug_exposure",
            source_value="Ambiguous drug",
            proposed_concept_id=1125315,
            score=0.5,
            model_name="test-model",
            vocabulary_version=manifest["version_label"],
            affected_target_ids=[2],
        )
        review_decision(
            source,
            rejected_id,
            action="reject",
            reviewer="Mario Costa",
            reason="Insufficient source specificity",
        )
        exported = export_mapping_rules(source, rules_path, manifest_path)

    assert len(exported["approved"]) == 1
    assert len(exported["rejected"]) == 1
    assert "target_id" not in rules_path.read_text(encoding="utf-8")

    with duckdb.connect(":memory:") as target:
        _create_concepts(target)
        first = import_mapping_rules(target, rules_path, manifest_path)
        second = import_mapping_rules(target, rules_path, manifest_path)

        assert first == second
        assert target.execute(
            "SELECT source_value, concept_id, approved_by, active "
            "FROM approved_mapping_set"
        ).fetchone() == ("Paracetamol", 1125315, "Mario Costa", True)
        assert target.execute(
            "SELECT source_value, rejected_by, active FROM rejected_mapping_set"
        ).fetchone() == ("Ambiguous drug", "Mario Costa", True)
        assert target.execute(
            "SELECT COUNT(*) FROM mapping_decision"
        ).fetchone()[0] == 2

        target.execute(
            "UPDATE concept SET valid_end_date = '2000-12-31' "
            "WHERE concept_id = '1125315'"
        )
        with pytest.raises(ValueError, match="not currently valid"):
            import_mapping_rules(target, rules_path, manifest_path)


def test_rules_reject_a_different_vocabulary(tmp_path):
    vocab_a = tmp_path / "vocab-a"
    vocab_b = tmp_path / "vocab-b"
    manifest_a = tmp_path / "manifest-a.json"
    manifest_b = tmp_path / "manifest-b.json"
    rules_path = tmp_path / "mapping_rules.json"
    _write_fake_vocabulary(vocab_a, "A")
    _write_fake_vocabulary(vocab_b, "B")
    identity_a = write_vocabulary_manifest(vocab_a, manifest_a)
    write_vocabulary_manifest(vocab_b, manifest_b)

    core = {
        "schema_version": 1,
        "vocabulary_fingerprint": identity_a["fingerprint"],
        "vocabulary_version": identity_a["version_label"],
        "approved": [],
        "rejected": [],
    }
    import hashlib
    canonical = json.dumps(core, sort_keys=True, separators=(",", ":"))
    core["ruleset_fingerprint"] = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    rules_path.write_text(json.dumps(core), encoding="utf-8")

    with duckdb.connect(":memory:") as con:
        _create_concepts(con)
        with pytest.raises(ValueError, match="different Athena vocabulary"):
            import_mapping_rules(con, rules_path, manifest_b)


def test_sync_entry_point_can_resolve_project_imports():
    project_root = Path(__file__).resolve().parent.parent
    script = project_root / "src" / "mapping" / "sync_mapping_rules.py"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import runpy; runpy.run_path(r'{script}', run_name='entrypoint_test')",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
