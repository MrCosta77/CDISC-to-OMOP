import sys
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.utils.config import DB_PATH


def fetch_adverse_events(con, limit=5):
    """Return AE frequencies without mixing in Medical History conditions."""
    return con.execute(
        """
        SELECT c.concept_name, COUNT(*) AS occurrences
        FROM condition_occurrence co
        JOIN source_record_lineage l
          ON l.target_table = 'condition_occurrence'
         AND l.target_id = co.condition_occurrence_id
         AND l.source_domain = 'AE'
        JOIN concept c ON co.condition_concept_id = c.concept_id
        WHERE co.condition_concept_id <> 0
        GROUP BY c.concept_name
        ORDER BY occurrences DESC, c.concept_name
        LIMIT ?
        """,
        [limit],
    ).fetchall()


def fetch_measurement_summaries(con, limit_per_domain=5):
    """Summarize LB, VS, and EG independently; do not infer baseline status."""
    return con.execute(
        """
        WITH summaries AS (
            SELECT
                l.source_domain,
                m.measurement_source_value,
                m.unit_source_value,
                COUNT(*) AS observations,
                ROUND(AVG(m.value_as_number), 1) AS average_value
            FROM measurement m
            JOIN source_record_lineage l
              ON l.target_table = 'measurement'
             AND l.target_id = m.measurement_id
             AND l.source_domain IN ('LB', 'VS', 'EG')
            WHERE m.value_as_number IS NOT NULL
            GROUP BY
                l.source_domain,
                m.measurement_source_value,
                m.unit_source_value
        ), ranked AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY source_domain
                ORDER BY observations DESC, measurement_source_value,
                         unit_source_value
            ) AS domain_rank
            FROM summaries
        )
        SELECT source_domain, measurement_source_value, average_value,
               unit_source_value, observations
        FROM ranked
        WHERE domain_rank <= ?
        ORDER BY source_domain, domain_rank
        """,
        [limit_per_domain],
    ).fetchall()


def run_analytics(db_path=DB_PATH):
    print("\n" + "📊" * 30)
    print("      REAL-WORLD EVIDENCE (RWE) - CLINICAL TRIAL ANALYTICS")
    print("📊" * 30 + "\n")

    with duckdb.connect(str(db_path), read_only=True) as con:
        print("1. DEMOGRAPHICS & COHORT OVERVIEW")
        print("-" * 60)
        pop_res = con.execute("""
            SELECT
                (SELECT COUNT(DISTINCT person_id) FROM person),
                ROUND(AVG(DATE_DIFF(
                    'day', observation_period_start_date::DATE,
                    observation_period_end_date::DATE
                )), 1)
            FROM observation_period
        """).fetchone()
        print(f"Total Patients in Trial:     {pop_res[0]}")
        print(f"Average Follow-up (Days):    {pop_res[1]}\n")

        print("Gender Distribution:")
        for name, count in con.execute("""
            SELECT COALESCE(c.concept_name, 'Unknown'), COUNT(*)
            FROM person p
            LEFT JOIN concept c ON p.gender_concept_id = c.concept_id
            GROUP BY 1
            ORDER BY 1
        """).fetchall():
            print(f" - {name:<10}: {count} patients")
        print()

        print("2. TOP ADVERSE EVENTS (AE domain only)")
        print("-" * 60)
        for name, count in fetch_adverse_events(con):
            print(f" - {name:<40} | {count} occurrences")
        print()

        print("3. MEASUREMENT SUMMARY BY SDTM DOMAIN (not baseline estimates)")
        print("-" * 60)
        current_domain = None
        for domain, name, average, unit, count in fetch_measurement_summaries(con):
            if domain != current_domain:
                print(f" {domain}:")
                current_domain = domain
            unit = unit or ""
            print(f" - {name:<28} | mean {average:>7} {unit:<10} | n={count}")
        print()

        print("4. PHENOTYPING: RESCUE MEDICATION USAGE (Acetaminophen)")
        print("-" * 60)
        rescue_res = con.execute("""
            SELECT COUNT(DISTINCT de.person_id)
            FROM drug_exposure de
            JOIN concept c ON de.drug_concept_id = c.concept_id
            WHERE LOWER(c.concept_name) LIKE '%acetaminophen%'
        """).fetchone()[0]
        rescue_rate = (rescue_res / pop_res[0]) * 100 if pop_res[0] else 0
        print(
            f"Patients needing Rescue Medication:  "
            f"{rescue_res} ({rescue_rate:.1f}%)"
        )
        print("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    run_analytics()
