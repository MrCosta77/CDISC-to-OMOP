import duckdb

from src.analytics.rwe_queries import (
    fetch_adverse_events,
    fetch_measurement_summaries,
)


def test_adverse_event_query_excludes_medical_history():
    con = duckdb.connect()
    con.execute("CREATE TABLE concept (concept_id BIGINT, concept_name VARCHAR)")
    con.execute("""
        CREATE TABLE condition_occurrence (
            condition_occurrence_id BIGINT, condition_concept_id BIGINT
        )
    """)
    con.execute("""
        CREATE TABLE source_record_lineage (
            target_table VARCHAR, target_id BIGINT, source_domain VARCHAR
        )
    """)
    con.execute("INSERT INTO concept VALUES (1, 'Headache'), (2, 'Hypertension')")
    con.execute("INSERT INTO condition_occurrence VALUES (10, 1), (11, 2)")
    con.execute("""
        INSERT INTO source_record_lineage VALUES
        ('condition_occurrence', 10, 'AE'),
        ('condition_occurrence', 11, 'MH')
    """)

    assert fetch_adverse_events(con) == [("Headache", 1)]


def test_measurement_query_separates_sdtm_domains_and_does_not_infer_baseline():
    con = duckdb.connect()
    con.execute("""
        CREATE TABLE measurement (
            measurement_id BIGINT, measurement_source_value VARCHAR,
            unit_source_value VARCHAR, value_as_number DOUBLE
        )
    """)
    con.execute("""
        CREATE TABLE source_record_lineage (
            target_table VARCHAR, target_id BIGINT, source_domain VARCHAR
        )
    """)
    con.execute("""
        INSERT INTO measurement VALUES
        (1, 'Heart Rate', 'beats/min', 60),
        (2, 'Heart Rate', 'beats/min', 80),
        (3, 'Glucose', 'mg/dL', 100),
        (4, 'QT Duration', 'msec', 400)
    """)
    con.execute("""
        INSERT INTO source_record_lineage VALUES
        ('measurement', 1, 'VS'), ('measurement', 2, 'VS'),
        ('measurement', 3, 'LB'), ('measurement', 4, 'EG')
    """)

    rows = fetch_measurement_summaries(con)
    assert rows == [
        ("EG", "QT Duration", 400.0, "msec", 1),
        ("LB", "Glucose", 100.0, "mg/dL", 1),
        ("VS", "Heart Rate", 70.0, "beats/min", 2),
    ]
