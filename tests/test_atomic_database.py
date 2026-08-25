import os

import duckdb
import pytest

import main as orchestrator
from src.utils.atomic_database import (
    atomic_database_candidate,
    candidate_database_path,
)


def _write_marker(path, value):
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE OR REPLACE TABLE marker (value VARCHAR)")
        con.execute("INSERT INTO marker VALUES (?)", [value])


def _read_marker(path):
    with duckdb.connect(str(path), read_only=True) as con:
        return con.execute("SELECT value FROM marker").fetchone()[0]


def test_atomic_candidate_replaces_final_only_after_success(tmp_path):
    final_path = tmp_path / "clinical.duckdb"
    _write_marker(final_path, "old")

    with atomic_database_candidate(final_path, "RUN-SUCCESS") as candidate:
        _write_marker(candidate, "new")
        assert _read_marker(final_path) == "old"

    assert _read_marker(final_path) == "new"
    assert not candidate.exists()


def test_atomic_candidate_failure_preserves_final_and_removes_candidate(tmp_path):
    final_path = tmp_path / "clinical.duckdb"
    _write_marker(final_path, "old")
    candidate = candidate_database_path(final_path, "RUN-FAILED")

    with pytest.raises(RuntimeError, match="simulated pipeline failure"):
        with atomic_database_candidate(final_path, "RUN-FAILED") as build_path:
            _write_marker(build_path, "partial")
            raise RuntimeError("simulated pipeline failure")

    assert _read_marker(final_path) == "old"
    assert not candidate.exists()
    assert not candidate.with_name(candidate.name + ".wal").exists()


def test_candidate_path_rejects_path_injection(tmp_path):
    with pytest.raises(ValueError, match="unsafe path characters"):
        candidate_database_path(tmp_path / "clinical.duckdb", "../escape")


def _mock_orchestrator(monkeypatch, tmp_path, fail=False):
    final_path = tmp_path / "published.duckdb"
    _write_marker(final_path, "old")
    monkeypatch.setattr(orchestrator, "DB_PATH", str(final_path))
    monkeypatch.setattr(orchestrator, "generate_run_id", lambda: "RUN-ORCHESTRATOR")
    monkeypatch.setattr(orchestrator, "validate_required_inputs", lambda: None)
    monkeypatch.setattr(
        orchestrator, "validate_cdisc_inputs", lambda: {"dm": 1}
    )
    monkeypatch.setattr(orchestrator, "start_pipeline_run", lambda *a, **k: None)
    monkeypatch.setattr(orchestrator, "finish_pipeline_run", lambda *a, **k: None)
    monkeypatch.setattr(
        orchestrator, "validate_published_database", lambda *a, **k: None
    )
    monkeypatch.setattr(
        orchestrator, "collect_output_counts", lambda *a, **k: {"person": 1}
    )
    calls = []

    def fake_run_script(*_args):
        calls.append(os.environ["DB_PATH"])
        if len(calls) == 1:
            _write_marker(calls[0], "partial" if fail else "new")
        if fail and len(calls) == 2:
            raise RuntimeError("simulated step failure")

    monkeypatch.setattr(orchestrator, "run_script", fake_run_script)
    return final_path, calls


def test_orchestrator_publishes_candidate_after_all_steps(monkeypatch, tmp_path):
    final_path, calls = _mock_orchestrator(monkeypatch, tmp_path)
    previous = os.environ.get("DB_PATH")

    orchestrator.main()

    assert calls
    assert all(path_value != str(final_path) for path_value in calls)
    assert _read_marker(final_path) == "new"
    assert os.environ.get("DB_PATH") == previous


def test_orchestrator_failure_keeps_previous_database(monkeypatch, tmp_path):
    final_path, calls = _mock_orchestrator(monkeypatch, tmp_path, fail=True)
    previous = os.environ.get("DB_PATH")

    with pytest.raises(RuntimeError, match="simulated step failure"):
        orchestrator.main()

    assert calls
    assert _read_marker(final_path) == "old"
    assert not candidate_database_path(
        final_path, "RUN-ORCHESTRATOR"
    ).exists()
    assert os.environ.get("DB_PATH") == previous
