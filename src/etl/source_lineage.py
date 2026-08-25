"""Build the current-publication bridge from OMOP rows back to SDTM records."""

import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.utils.run_context import require_run_id


LINEAGE_INPUTS = {
    "person": {
        "filename": "PERSON.csv",
        "id_column": "person_id",
        "domain_column": "source_domain",
    },
    "observation_period": {
        "filename": "OBSERVATION_PERIOD.csv",
        "id_column": "observation_period_id",
        "domain_column": "source_domain",
    },
    "visit_occurrence": {
        "filename": "VISIT_OCCURRENCE.csv",
        "id_column": "visit_occurrence_id",
        "domain_column": "source_domain",
    },
    "condition_occurrence": {
        "filename": "CONDITION_OCCURRENCE.csv",
        "id_column": "condition_occurrence_id",
        "domain_column": "source_domain",
    },
    "drug_exposure": {
        "filename": "DRUG_EXPOSURE.csv",
        "id_column": "drug_exposure_id",
        "domain_column": "drug_source_domain",
        "mapping_column": "drug_mapping_value",
    },
    "measurement": {
        "filename": "MEASUREMENT.csv",
        "id_column": "measurement_id",
        "domain_column": "measurement_source_domain",
    },
}


def build_source_lineage(processed_dir=None, output_path=None, run_id=None):
    processed_dir = Path(processed_dir or PROJECT_ROOT / "data" / "processed")
    output_path = Path(
        output_path or processed_dir / "SOURCE_RECORD_LINEAGE.csv"
    )
    run_id = run_id or require_run_id()
    records = []

    for target_table, config in LINEAGE_INPUTS.items():
        path = processed_dir / config["filename"]
        if not path.is_file():
            raise FileNotFoundError(f"Lineage input is missing: {path}")
        frame = pd.read_csv(path, dtype={"source_subject_id": "string"})
        mapping_column = config.get("mapping_column", "mapping_source_value")
        required = {
            config["id_column"],
            "person_id",
            config["domain_column"],
            "source_subject_id",
            "source_record_key",
            "source_record_value",
            mapping_column,
        }
        missing = sorted(required.difference(frame.columns))
        if missing:
            raise ValueError(
                f"{path.name} is missing lineage fields: " + ", ".join(missing)
            )

        required_values = [
            config["id_column"],
            "person_id",
            config["domain_column"],
            "source_subject_id",
            "source_record_key",
        ]
        invalid = int(frame[required_values].isna().any(axis=1).sum())
        duplicates = int(frame[config["id_column"]].duplicated().sum())
        if invalid or duplicates:
            raise ValueError(
                f"{path.name} lineage contract violation. "
                f"Invalid required values: {invalid}; duplicate target IDs: {duplicates}."
            )

        for _, row in frame.iterrows():
            domain = str(row[config["domain_column"]]).strip().upper()
            mapping_value = row.get(mapping_column)
            records.append({
                "run_id": run_id,
                "target_table": target_table,
                "target_id": int(row[config["id_column"]]),
                "person_id": int(row["person_id"]),
                "source_domain": domain,
                "source_file": f"{domain.lower()}.sas7bdat",
                "source_subject_id": str(row["source_subject_id"]).strip(),
                "source_record_key": str(row["source_record_key"]).strip(),
                "source_value": row.get("source_record_value"),
                "mapping_source_value": (
                    mapping_value if pd.notna(mapping_value) else None
                ),
                "source_end_date": (
                    row.get("source_end_date")
                    if pd.notna(row.get("source_end_date")) else None
                ),
                "published_end_date": (
                    row.get("published_end_date")
                    if pd.notna(row.get("published_end_date")) else None
                ),
                "end_date_derivation": (
                    row.get("end_date_derivation")
                    if pd.notna(row.get("end_date_derivation")) else None
                ),
            })

    lineage = pd.DataFrame(records)
    if lineage.duplicated(["target_table", "target_id"]).any():
        raise ValueError("Lineage contains duplicate OMOP target rows.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lineage.to_csv(output_path, index=False)
    print(
        f"✅ SOURCE_RECORD_LINEAGE generated with {len(lineage)} rows "
        f"for run {run_id}."
    )
    return lineage


if __name__ == "__main__":
    build_source_lineage()
