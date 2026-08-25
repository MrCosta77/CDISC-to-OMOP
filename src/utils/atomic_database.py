"""File-level atomic publication for a complete DuckDB build."""

import os
import re
from contextlib import contextmanager
from pathlib import Path


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def candidate_database_path(final_path, run_id):
    """Return a unique candidate path beside the final database."""
    final_path = Path(final_path).absolute()
    if not _SAFE_RUN_ID.fullmatch(str(run_id)):
        raise ValueError("run_id contains unsafe path characters.")
    return final_path.with_name(
        f".{final_path.stem}.{run_id}.candidate{final_path.suffix}"
    )


def _candidate_artifacts(final_path, run_id):
    candidate = candidate_database_path(final_path, run_id)
    return candidate, Path(f"{candidate}.wal")


def _discard_candidate(final_path, run_id):
    """Delete only the exact, validated candidate and its DuckDB WAL."""
    for path in reversed(_candidate_artifacts(final_path, run_id)):
        path.unlink(missing_ok=True)


@contextmanager
def atomic_database_candidate(final_path, run_id):
    """
    Yield an isolated DuckDB path and publish it on successful exit.

    The final database is never opened or changed by this context manager until
    the candidate is complete and every caller-side validation has passed.
    """
    final_path = Path(final_path).absolute()
    candidate, wal = _candidate_artifacts(final_path, run_id)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if candidate.exists() or wal.exists():
        raise FileExistsError(
            f"Atomic database candidate already exists: {candidate}"
        )

    try:
        yield candidate
        if not candidate.is_file():
            raise FileNotFoundError(
                f"Pipeline did not create its candidate database: {candidate}"
            )
        if wal.exists():
            raise RuntimeError(
                "Candidate database still has a DuckDB WAL; all writers must "
                "close before publication."
            )
        os.replace(candidate, final_path)
    except BaseException:
        _discard_candidate(final_path, run_id)
        raise

