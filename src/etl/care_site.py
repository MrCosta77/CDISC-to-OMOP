import os
import sys

import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.utils.helpers import generate_care_site_id
from src.utils.config import PROCESSED_DIR


def run_etl_care_site(input_path, output_path):
    """Create one de-identified OMOP CARE_SITE row per study and SITEID."""
    print(f"Reading CDISC Demographics file from: {input_path}")
    df_dm = pd.read_sas(input_path, format="sas7bdat", encoding="utf-8")

    sites = (
        df_dm[["STUDYID", "SITEID"]]
        .drop_duplicates()
        .sort_values(["STUDYID", "SITEID"])
    )
    records = []
    for _, row in sites.iterrows():
        studyid = str(row["STUDYID"]).strip()
        siteid = str(row["SITEID"]).strip()
        source_value = f"{studyid}|{siteid}"
        records.append({
            "care_site_id": generate_care_site_id(studyid, siteid),
            "care_site_source_value": source_value,
        })

    df_care_site = pd.DataFrame(records)
    df_care_site["care_site_id"] = df_care_site["care_site_id"].astype("Int64")
    df_care_site.to_csv(output_path, index=False)
    print(f"CARE_SITE table generated with {len(df_care_site)} source sites.")
    print(f"File saved to: {output_path}")


if __name__ == "__main__":
    run_etl_care_site(
        "data/raw/dm.sas7bdat", os.path.join(PROCESSED_DIR, "CARE_SITE.csv")
    )
