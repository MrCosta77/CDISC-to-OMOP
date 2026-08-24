"""Build and verify a portable identity for the local Athena vocabulary extract."""

import csv
import hashlib
import json
from pathlib import Path


MANIFEST_SCHEMA_VERSION = 1
VOCABULARY_FILES = (
    "CONCEPT.csv",
    "CONCEPT_RELATIONSHIP.csv",
    "VOCABULARY.csv",
    "DOMAIN.csv",
    "CONCEPT_CLASS.csv",
    "RELATIONSHIP.csv",
)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_fingerprint(payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read_vocabulary_versions(path):
    versions = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            version = (row.get("vocabulary_version") or "").strip()
            if version:
                versions[row["vocabulary_id"].strip()] = version
    return dict(sorted(versions.items()))


def build_vocabulary_manifest(vocab_dir):
    """Hash every vocabulary file loaded by this pipeline."""
    vocab_dir = Path(vocab_dir)
    files = {}
    for name in VOCABULARY_FILES:
        path = vocab_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"Required Athena file is missing: {path}")
        files[name] = {
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }

    identity = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "files": files,
        "vocabulary_versions": _read_vocabulary_versions(
            vocab_dir / "VOCABULARY.csv"
        ),
    }
    identity["fingerprint"] = _canonical_fingerprint(identity)
    identity["version_label"] = f"Athena-{identity['fingerprint'][:12]}"
    return identity


def write_vocabulary_manifest(vocab_dir, output_path):
    manifest = build_vocabulary_manifest(vocab_dir)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def load_vocabulary_manifest(manifest_path):
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Athena vocabulary manifest is missing: {manifest_path}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("Unsupported Athena vocabulary manifest schema.")

    fingerprint_payload = {
        "schema_version": manifest["schema_version"],
        "files": manifest.get("files", {}),
        "vocabulary_versions": manifest.get("vocabulary_versions", {}),
    }
    expected = _canonical_fingerprint(fingerprint_payload)
    if manifest.get("fingerprint") != expected:
        raise ValueError("Athena vocabulary manifest fingerprint is invalid.")
    if manifest.get("version_label") != f"Athena-{expected[:12]}":
        raise ValueError("Athena vocabulary version label is invalid.")
    return manifest


def validate_vocabulary_manifest(vocab_dir, manifest_path, verify_hashes=True):
    """Ensure the local extract is exactly the extract pinned by the manifest."""
    manifest = load_vocabulary_manifest(manifest_path)
    vocab_dir = Path(vocab_dir)
    expected_files = manifest["files"]
    if set(expected_files) != set(VOCABULARY_FILES):
        raise ValueError("Athena vocabulary manifest has an unexpected file set.")

    for name in VOCABULARY_FILES:
        path = vocab_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"Required Athena file is missing: {path}")
        expected = expected_files[name]
        if path.stat().st_size != expected["size_bytes"]:
            raise ValueError(f"Athena vocabulary size mismatch: {name}")
        if verify_hashes and _sha256(path) != expected["sha256"]:
            raise ValueError(f"Athena vocabulary checksum mismatch: {name}")
    return manifest
