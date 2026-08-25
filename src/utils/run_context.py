import hashlib
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from src.utils.config import (
    ALLOW_DIRTY_RUN,
    CONFIDENCE_THRESHOLD,
    DB_PATH,
    MODEL_NAME,
    MAPPING_RULES_PATH,
    PROJECT_ROOT,
    PROCESSED_DIR,
    VOCAB_DIR,
    VOCAB_MANIFEST_PATH,
)
from src.utils.vocabulary_identity import (
    VOCABULARY_FILES,
    load_vocabulary_manifest,
)


RUN_ID_ENV = "PIPELINE_RUN_ID"
REQUIRED_RAW_DATASETS = (
    "dm", "ae", "mh", "ex", "cm", "lb", "vs", "eg", "sv", "ds"
)
CLINICAL_TABLES = (
    "care_site",
    "person",
    "observation_period",
    "visit_occurrence",
    "condition_occurrence",
    "drug_exposure",
    "measurement",
    "source_record_lineage",
)
PIPELINE_RUN_COLUMNS = (
    "run_id",
    "status",
    "started_at",
    "finished_at",
    "git_commit",
    "git_is_dirty",
    "source_tree_sha256",
    "source_manifest_json",
    "input_manifest_json",
    "config_snapshot_json",
    "output_counts_json",
    "error_message",
)


def generate_run_id():
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"RUN-{timestamp}-{uuid.uuid4().hex[:8]}"


def require_run_id():
    run_id = os.getenv(RUN_ID_ENV, "").strip()
    if not run_id:
        raise RuntimeError(
            f"{RUN_ID_ENV} is not set. Run the mapping through main.py so the "
            "audit trail is associated with a pipeline execution."
        )
    return run_id


def ensure_audit_schema(con):
    con.execute("CREATE SEQUENCE IF NOT EXISTS seq_provenance_id START 1")
    con.execute("CREATE SEQUENCE IF NOT EXISTS seq_mapping_decision_id START 1")
    con.execute("CREATE SEQUENCE IF NOT EXISTS seq_mapping_set_id START 1")
    con.execute("""
        CREATE TABLE IF NOT EXISTS mapping_provenance (
            provenance_id BIGINT PRIMARY KEY DEFAULT nextval('seq_provenance_id'),
            target_table VARCHAR NOT NULL,
            target_id BIGINT NOT NULL,
            source_value VARCHAR,
            normalized_value VARCHAR,
            assigned_concept_id INTEGER NOT NULL,
            mapping_method VARCHAR NOT NULL,
            score DOUBLE NOT NULL,
            model_name VARCHAR,
            vocabulary_version VARCHAR,
            reviewed_by VARCHAR DEFAULT 'Pending_Human_Review',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            run_id VARCHAR,
            mapping_decision_id BIGINT
        )
    """)

    columns = {
        row[1] for row in con.execute("PRAGMA table_info('mapping_provenance')").fetchall()
    }
    if "run_id" not in columns:
        con.execute("ALTER TABLE mapping_provenance ADD COLUMN run_id VARCHAR")
    if "mapping_decision_id" not in columns:
        con.execute(
            "ALTER TABLE mapping_provenance "
            "ADD COLUMN mapping_decision_id BIGINT"
        )

    con.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_run (
            run_id VARCHAR PRIMARY KEY,
            status VARCHAR NOT NULL,
            started_at TIMESTAMP NOT NULL,
            finished_at TIMESTAMP,
            git_commit VARCHAR,
            git_is_dirty BOOLEAN,
            source_tree_sha256 VARCHAR,
            source_manifest_json VARCHAR,
            input_manifest_json VARCHAR,
            config_snapshot_json VARCHAR,
            output_counts_json VARCHAR,
            error_message VARCHAR
        )
    """)
    pipeline_columns = {
        row[1]
        for row in con.execute("PRAGMA table_info('pipeline_run')").fetchall()
    }
    for column, datatype in (
        ("git_is_dirty", "BOOLEAN"),
        ("source_tree_sha256", "VARCHAR"),
        ("source_manifest_json", "VARCHAR"),
    ):
        if column not in pipeline_columns:
            con.execute(
                f'ALTER TABLE pipeline_run ADD COLUMN "{column}" {datatype}'
            )
    con.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_mapping_provenance_run_target
        ON mapping_provenance (run_id, target_table, target_id, mapping_method)
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS mapping_decision (
            mapping_decision_id BIGINT PRIMARY KEY
                DEFAULT nextval('seq_mapping_decision_id'),
            run_id VARCHAR NOT NULL,
            target_table VARCHAR NOT NULL,
            source_value VARCHAR NOT NULL,
            normalized_value VARCHAR NOT NULL,
            proposed_concept_id INTEGER NOT NULL,
            selected_concept_id INTEGER,
            mapping_method VARCHAR NOT NULL,
            score DOUBLE NOT NULL,
            model_name VARCHAR,
            vocabulary_version VARCHAR,
            prompt_version VARCHAR NOT NULL,
            decision_status VARCHAR NOT NULL,
            reviewed_by VARCHAR,
            reviewed_at TIMESTAMP,
            review_reason VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_mapping_decision_run_source
        ON mapping_decision (
            run_id, target_table, normalized_value, mapping_method
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS mapping_decision_event (
            mapping_decision_id BIGINT NOT NULL,
            target_id BIGINT NOT NULL,
            PRIMARY KEY (mapping_decision_id, target_id)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS approved_mapping_set (
            mapping_set_id BIGINT PRIMARY KEY
                DEFAULT nextval('seq_mapping_set_id'),
            target_table VARCHAR NOT NULL,
            source_value VARCHAR NOT NULL,
            normalized_value VARCHAR NOT NULL,
            concept_id INTEGER NOT NULL,
            source_decision_id BIGINT NOT NULL,
            approved_by VARCHAR NOT NULL,
            approval_reason VARCHAR NOT NULL,
            approved_at TIMESTAMP NOT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_approved_mapping_target_source
        ON approved_mapping_set (target_table, normalized_value)
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS rejected_mapping_set (
            target_table VARCHAR NOT NULL,
            source_value VARCHAR NOT NULL,
            normalized_value VARCHAR NOT NULL,
            source_decision_id BIGINT NOT NULL,
            rejected_by VARCHAR NOT NULL,
            rejection_reason VARCHAR NOT NULL,
            rejected_at TIMESTAMP NOT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (target_table, normalized_value)
        )
    """)


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_manifest(path, include_hash=True):
    stat = path.stat()
    manifest = {
        "path": str(path),
        "size_bytes": stat.st_size,
        "modified_at_utc": datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).isoformat(),
    }
    if include_hash:
        manifest["sha256"] = _sha256(path)
    return manifest


def _optional_file_manifest(path, include_hash=True):
    if not path.is_file():
        return {"path": str(path), "missing": True}
    return _file_manifest(path, include_hash=include_hash)


def validate_required_inputs():
    raw_dir = PROJECT_ROOT / "data" / "raw"
    required_paths = [raw_dir / f"{name}.sas7bdat" for name in REQUIRED_RAW_DATASETS]
    required_paths.extend(
        [Path(VOCAB_DIR) / name for name in VOCABULARY_FILES]
    )
    required_paths.extend([Path(VOCAB_MANIFEST_PATH), Path(MAPPING_RULES_PATH)])
    missing = [str(path) for path in required_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Required pipeline inputs are missing:\n- " + "\n- ".join(missing)
        )


def build_input_manifest():
    raw_dir = PROJECT_ROOT / "data" / "raw"
    raw_files = {
        f"{name}.sas7bdat": _optional_file_manifest(raw_dir / f"{name}.sas7bdat")
        for name in REQUIRED_RAW_DATASETS
    }
    vocabulary_identity = load_vocabulary_manifest(VOCAB_MANIFEST_PATH)
    vocab_files = {
        name: _optional_file_manifest(Path(VOCAB_DIR) / name, include_hash=False)
        for name in VOCABULARY_FILES
    }
    return {
        "raw": raw_files,
        "vocabulary": vocab_files,
        "vocabulary_identity": {
            "fingerprint": vocabulary_identity["fingerprint"],
            "version_label": vocabulary_identity["version_label"],
        },
        "mapping_rules": _optional_file_manifest(Path(MAPPING_RULES_PATH)),
    }


def get_git_state(project_root=PROJECT_ROOT):
    """Return the current commit and whether tracked/untracked source changed."""
    project_root = Path(project_root)
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        return {
            "git_commit": commit,
            "git_is_dirty": bool(status),
            "git_status": status,
        }
    except (OSError, subprocess.CalledProcessError):
        return {
            "git_commit": None,
            "git_is_dirty": None,
            "git_status": [],
        }


def build_source_manifest(project_root=PROJECT_ROOT):
    """Hash the Python source tree actually capable of driving the pipeline."""
    project_root = Path(project_root)
    paths = [project_root / "main.py"]
    paths.extend(sorted((project_root / "src").rglob("*.py")))
    files = {}
    for path in paths:
        if path.is_file():
            relative = path.relative_to(project_root).as_posix()
            files[relative] = _sha256(path)
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"))
    return {
        "algorithm": "sha256",
        "source_tree_sha256": hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest(),
        "files": files,
    }


def collect_source_state(project_root=PROJECT_ROOT):
    state = get_git_state(project_root)
    manifest = build_source_manifest(project_root)
    state.update({
        "source_tree_sha256": manifest["source_tree_sha256"],
        "source_manifest": manifest,
    })
    return state


def require_publishable_source_state(source_state, allow_dirty=ALLOW_DIRTY_RUN):
    """Fail closed when Git can prove that unpublished source would be used."""
    if source_state.get("git_is_dirty") and not allow_dirty:
        examples = source_state.get("git_status", [])[:5]
        detail = "; ".join(examples) if examples else "working tree modified"
        raise RuntimeError(
            "Refusing to publish from a dirty Git working tree. Commit or stash "
            "the source changes first, or explicitly set ALLOW_DIRTY_RUN=true "
            f"for a development run. Changes: {detail}"
        )


def config_snapshot():
    return {
        "model_name": MODEL_NAME,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "db_path": DB_PATH,
        "processed_dir": PROCESSED_DIR,
        "vocab_dir": VOCAB_DIR,
        "vocab_manifest_path": VOCAB_MANIFEST_PATH,
        "mapping_rules_path": MAPPING_RULES_PATH,
        "allow_dirty_run": ALLOW_DIRTY_RUN,
    }


def start_pipeline_run(
    run_id,
    db_path=DB_PATH,
    input_manifest=None,
    snapshot=None,
    git_commit=None,
    source_state=None,
):
    source_state = source_state or collect_source_state()
    if git_commit is not None:
        source_state = dict(source_state)
        source_state["git_commit"] = git_commit
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as con:
        ensure_audit_schema(con)
        con.execute("""
            INSERT INTO pipeline_run (
                run_id, status, started_at, git_commit,
                git_is_dirty, source_tree_sha256, source_manifest_json,
                input_manifest_json, config_snapshot_json
            ) VALUES (?, 'RUNNING', CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?)
        """, (
            run_id,
            source_state.get("git_commit"),
            source_state.get("git_is_dirty"),
            source_state.get("source_tree_sha256"),
            json.dumps(source_state.get("source_manifest"), sort_keys=True),
            json.dumps(
                build_input_manifest() if input_manifest is None else input_manifest,
                sort_keys=True,
            ),
            json.dumps(config_snapshot() if snapshot is None else snapshot, sort_keys=True),
        ))


def carry_forward_pipeline_history(source_db_path, target_db_path):
    """Copy the append-only run ledger into a new atomic database candidate."""
    source_db_path = Path(source_db_path)
    target_db_path = Path(target_db_path)
    if not source_db_path.is_file():
        return 0

    with duckdb.connect(str(source_db_path), read_only=True) as source:
        exists = source.execute("""
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'main' AND table_name = 'pipeline_run'
        """).fetchone()[0]
        if not exists:
            return 0
        available = {
            row[1]
            for row in source.execute("PRAGMA table_info('pipeline_run')").fetchall()
        }
        if "run_id" not in available:
            return 0
        selected = [column for column in PIPELINE_RUN_COLUMNS if column in available]
        order_by = (
            '"started_at", "run_id"'
            if "started_at" in available
            else '"run_id"'
        )
        rows = source.execute(
            "SELECT " + ", ".join(f'\"{column}\"' for column in selected)
            + f" FROM pipeline_run ORDER BY {order_by}"
        ).fetchall()

    if not rows:
        return 0
    positions = {column: index for index, column in enumerate(selected)}
    complete_rows = [
        tuple(
            row[positions[column]] if column in positions else None
            for column in PIPELINE_RUN_COLUMNS
        )
        for row in rows
    ]
    target_db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(target_db_path)) as target:
        ensure_audit_schema(target)
        columns = ", ".join(f'\"{column}\"' for column in PIPELINE_RUN_COLUMNS)
        placeholders = ", ".join("?" for _ in PIPELINE_RUN_COLUMNS)
        target.executemany(
            f"INSERT INTO pipeline_run ({columns}) VALUES ({placeholders}) "
            "ON CONFLICT (run_id) DO NOTHING",
            complete_rows,
        )
    return len(complete_rows)


def collect_output_counts(db_path=DB_PATH):
    counts = {}
    with duckdb.connect(str(db_path), read_only=True) as con:
        existing = {
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
        }
        for table in CLINICAL_TABLES:
            if table in existing:
                counts[table] = con.execute(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).fetchone()[0]
    return counts


def finish_pipeline_run(run_id, status, error_message=None, output_counts=None, db_path=DB_PATH):
    if status not in {"SUCCESS", "FAILED"}:
        raise ValueError("Pipeline status must be SUCCESS or FAILED.")
    with duckdb.connect(str(db_path)) as con:
        ensure_audit_schema(con)
        con.execute("""
            UPDATE pipeline_run
            SET status = ?, finished_at = CURRENT_TIMESTAMP,
                output_counts_json = ?, error_message = ?
            WHERE run_id = ?
        """, (
            status,
            json.dumps(output_counts, sort_keys=True) if output_counts is not None else None,
            error_message,
            run_id,
        ))
