"""Link OMOP events to actual SV visits without inventing encounters."""

from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _link_domain(events, visits, event_date_column):
    result = events.copy()
    result["visit_occurrence_id"] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    visit_lookup = {
        (int(row.person_id), float(row.source_visit_num)): int(row.visit_occurrence_id)
        for row in visits.itertuples()
    }

    if "source_visit_num" in result.columns:
        visit_numbers = pd.to_numeric(result["source_visit_num"], errors="coerce")
        for index in result.index[visit_numbers.notna()]:
            person_id = result.at[index, "person_id"]
            if pd.notna(person_id):
                result.at[index, "visit_occurrence_id"] = visit_lookup.get(
                    (int(person_id), float(visit_numbers.at[index])), pd.NA
                )

    event_dates = pd.to_datetime(result[event_date_column], errors="coerce")
    visit_starts = pd.to_datetime(visits["visit_start_date"], errors="raise")
    visit_ends = pd.to_datetime(visits["visit_end_date"], errors="raise")
    for index in result.index[result["visit_occurrence_id"].isna()]:
        if "source_visit_num" in result.columns and pd.notna(
            pd.to_numeric(pd.Series([result.at[index, "source_visit_num"]]), errors="coerce").iloc[0]
        ):
            continue
        person_id, event_date = result.at[index, "person_id"], event_dates.at[index]
        if pd.isna(person_id) or pd.isna(event_date):
            continue
        matches = visits.loc[
            (visits["person_id"] == person_id)
            & (visit_starts <= event_date)
            & (visit_ends >= event_date),
            "visit_occurrence_id",
        ]
        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous visit link for person_id={person_id}, date={event_date.date()}."
            )
        if len(matches) == 1:
            result.at[index, "visit_occurrence_id"] = int(matches.iloc[0])

    result["visit_occurrence_id"] = result["visit_occurrence_id"].astype("Int64")
    return result


def run_visit_linking(processed_dir=None):
    print("🔗 Linking clinical events to actual SV visits...")
    processed_dir = Path(processed_dir or PROJECT_ROOT / "data" / "processed")
    visits = pd.read_csv(processed_dir / "VISIT_OCCURRENCE.csv")
    required = {
        "visit_occurrence_id", "person_id", "visit_start_date", "visit_end_date",
        "source_visit_num",
    }
    missing = sorted(required.difference(visits.columns))
    if missing:
        raise ValueError("Visit-link contract violation. Missing columns: " + ", ".join(missing))
    if visits.duplicated(["person_id", "source_visit_num"]).any():
        raise ValueError("Visit-link contract violation: duplicate subject/visit numbers.")

    specifications = {
        "CONDITION_OCCURRENCE.csv": "condition_start_date",
        "DRUG_EXPOSURE.csv": "drug_exposure_start_date",
        "MEASUREMENT.csv": "measurement_date",
    }
    linked = {}
    for filename, date_column in specifications.items():
        events = pd.read_csv(processed_dir / filename)
        linked[filename] = _link_domain(events, visits, date_column)

    for filename, events in linked.items():
        events.to_csv(processed_dir / filename, index=False)
    print("✅ Clinical domains linked where an unambiguous actual visit exists.")

if __name__ == "__main__":
    run_visit_linking()
