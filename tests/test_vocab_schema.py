import duckdb

from src.omop.cdm54 import expected_columns, validate_table_schema
from src.utils.setup_vocab import load_vocabularies
from src.utils.vocabulary_identity import write_vocabulary_manifest


def _write_tsv(path, columns, rows):
    path.write_text(
        "\t".join(columns)
        + "\n"
        + "\n".join("\t".join(map(str, row)) for row in rows)
        + "\n",
        encoding="utf-8",
    )


def test_vocabulary_loader_uses_explicit_omop_types(tmp_path):
    vocab_dir = tmp_path / "vocab"
    vocab_dir.mkdir()
    _write_tsv(
        vocab_dir / "CONCEPT.csv",
        expected_columns("concept"),
        [
            (1, "Example condition", "Condition", "SNOMED", "Clinical Finding", "S", "A", "20200101", "20991231", ""),
            (2, "Example source", "Condition", "SNOMED", "Clinical Finding", "", "B", "20200101", "20991231", ""),
        ],
    )
    _write_tsv(
        vocab_dir / "CONCEPT_RELATIONSHIP.csv",
        expected_columns("concept_relationship"),
        [(2, 1, "Maps to", "20200101", "20991231", "")],
    )
    structural_rows = {
        "vocabulary": [("SNOMED", "SNOMED", "Test", "Test-1", 1)],
        "domain": [("Condition", "Condition", 1)],
        "concept_class": [("Clinical Finding", "Clinical Finding", 1)],
        "relationship": [
            ("Maps to", "Maps to", "0", "0", "Mapped from", 1)
        ],
    }
    filenames = {
        "vocabulary": "VOCABULARY.csv",
        "domain": "DOMAIN.csv",
        "concept_class": "CONCEPT_CLASS.csv",
        "relationship": "RELATIONSHIP.csv",
    }
    for table, rows in structural_rows.items():
        _write_tsv(
            vocab_dir / filenames[table], expected_columns(table), rows
        )
    manifest_path = tmp_path / "athena_manifest.json"
    write_vocabulary_manifest(vocab_dir, manifest_path)
    db_path = tmp_path / "vocab.duckdb"

    load_vocabularies(
        db_path=db_path,
        vocab_dir=vocab_dir,
        manifest_path=manifest_path,
    )

    with duckdb.connect(str(db_path), read_only=True) as con:
        assert validate_table_schema(con, "concept")
        assert validate_table_schema(con, "concept_relationship")
        assert validate_table_schema(con, "vocabulary")
        assert validate_table_schema(con, "domain")
        assert validate_table_schema(con, "concept_class")
        assert validate_table_schema(con, "relationship")
        assert con.execute("SELECT typeof(concept_id) FROM concept LIMIT 1").fetchone()[0] == "BIGINT"
        assert con.execute("SELECT COUNT(*) FROM concept").fetchone()[0] == 2
