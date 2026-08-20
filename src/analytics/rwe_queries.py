import os
import sys
import duckdb
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.utils.config import DB_PATH

def run_analytics():
    print("\n" + "📊"*30)
    print("      REAL-WORLD EVIDENCE (RWE) - CLINICAL TRIAL ANALYTICS")
    print("📊"*30 + "\n")

    with duckdb.connect(DB_PATH, read_only=True) as con:
        
        # 1. VISÃO GERAL DA POPULAÇÃO E DEMOGRAFIA
        print("1. DEMOGRAPHICS & COHORT OVERVIEW")
        print("-" * 60)
        pop_query = """
            SELECT 
                (SELECT COUNT(DISTINCT person_id) FROM person) as total_patients,
                ROUND(AVG(DATE_DIFF('day', observation_period_start_date::DATE, observation_period_end_date::DATE)), 1) as avg_days_observed
            FROM observation_period
        """
        pop_res = con.execute(pop_query).fetchone()
        print(f"Total Patients in Trial:     {pop_res[0]}")
        print(f"Average Follow-up (Days):    {pop_res[1]}\n")

        gender_query = """
            SELECT COALESCE(c.concept_name, 'Unknown'), COUNT(p.person_id) as count
            FROM person p
            LEFT JOIN concept c ON p.gender_concept_id = c.concept_id
            GROUP BY 1
        """
        print("Gender Distribution:")
        for row in con.execute(gender_query).fetchall():
            print(f" - {row[0]:<10}: {row[1]} patients")
        print("\n")

        # 2. TOP EVENTOS ADVERSOS (Condições)
        print("2. TOP ADVERSE EVENTS (Standardized by AI & Determinism)")
        print("-" * 60)
        cond_query = """
            SELECT c.concept_name, COUNT(co.condition_occurrence_id) as occurrences
            FROM condition_occurrence co
            JOIN concept c ON co.condition_concept_id = c.concept_id
            WHERE co.condition_concept_id != 0
            GROUP BY c.concept_name
            ORDER BY occurrences DESC
            LIMIT 5
        """
        for row in con.execute(cond_query).fetchall():
            print(f" - {row[0]:<40} | {row[1]} occurrences")
        print("\n")

        print("3. LABORATORY BASELINES (Average Values)")
        print("-" * 60)
        lab_query = """
            SELECT 
                measurement_source_value, 
                ROUND(AVG(value_as_number), 1) as avg_value, 
                unit_source_value
            FROM measurement
            WHERE value_as_number IS NOT NULL
            GROUP BY measurement_source_value, unit_source_value
            ORDER BY avg_value DESC
            LIMIT 5
        """
        for row in con.execute(lab_query).fetchall():
            print(f" - {row[0]:<30} | {row[1]:>6} {row[2]}")
        print("\n")

        print("4. PHENOTYPING: RESCUE MEDICATION USAGE (Paracetamol/Acetaminophen)")
        print("-" * 60)
        rescue_query = """
            SELECT COUNT(DISTINCT de.person_id)
            FROM drug_exposure de
            JOIN concept c ON de.drug_concept_id = c.concept_id
            WHERE LOWER(c.concept_name) LIKE '%acetaminophen%'
        """
        rescue_res = con.execute(rescue_query).fetchone()[0]
        rescue_rate = (rescue_res / pop_res[0]) * 100 if pop_res[0] > 0 else 0
        
        print(f"Patients needing Rescue Medication:  {rescue_res} ({rescue_rate:.1f}%)")
        print("\n" + "="*60 + "\n")

if __name__ == "__main__":
    run_analytics()