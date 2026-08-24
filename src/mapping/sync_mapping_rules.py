"""Import the versioned human review rules into the operational database."""

import sys
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.mapping.rule_portability import import_mapping_rules
from src.utils.config import DB_PATH, MAPPING_RULES_PATH, VOCAB_MANIFEST_PATH


def sync_mapping_rules(
    db_path=DB_PATH,
    rules_path=MAPPING_RULES_PATH,
    vocabulary_manifest_path=VOCAB_MANIFEST_PATH,
):
    with duckdb.connect(str(db_path)) as con:
        result = import_mapping_rules(
            con, rules_path, vocabulary_manifest_path
        )
    print(
        "✅ Versioned mapping rules synchronized: "
        f"{result['approved']} approved, {result['rejected']} rejected "
        f"({result['ruleset_fingerprint'][:12]})."
    )
    return result


if __name__ == "__main__":
    sync_mapping_rules()
