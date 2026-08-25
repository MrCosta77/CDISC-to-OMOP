import duckdb

from src.mapping.llm_shared import get_candidates_from_db_safe


def _concept_connection():
    con = duckdb.connect(":memory:")
    con.execute("""
        CREATE TABLE concept (
            concept_id VARCHAR,
            concept_name VARCHAR,
            domain_id VARCHAR,
            standard_concept VARCHAR,
            invalid_reason VARCHAR,
            valid_start_date DATE,
            valid_end_date DATE
        )
    """)
    con.executemany("""
        INSERT INTO concept VALUES (
            ?, ?, 'Measurement', 'S', NULL, '1970-01-01', '2099-12-31'
        )
    """, [
        ("4116636", "ST segment duration"),
        ("4116637", "QT interval duration"),
        ("3025809", "Q-T interval"),
        ("3013078", "R-R interval by EKG"),
    ])
    return con


def test_qt_abbreviation_is_not_discarded_from_candidate_ranking():
    with _concept_connection() as con:
        candidates = get_candidates_from_db_safe("QT Duration", con, "Measurement")

    assert int(candidates[0][0]) == 4116637
    assert candidates[0][1] == "QT interval duration"


def test_rr_abbreviation_outranks_unrelated_duration_candidate():
    with _concept_connection() as con:
        candidates = get_candidates_from_db_safe("RR Duration", con, "Measurement")

    assert int(candidates[0][0]) == 3013078
    assert candidates[0][1] == "R-R interval by EKG"


def test_equal_candidate_names_use_stable_concept_id_tiebreak():
    with _concept_connection() as con:
        con.executemany("""
            INSERT INTO concept VALUES (
                ?, 'Systolic blood pressure', 'Measurement', 'S', NULL,
                '1970-01-01', '2099-12-31'
            )
        """, [(4152194,), (3004249,)])
        candidates = get_candidates_from_db_safe(
            "Systolic blood pressure", con, "Measurement"
        )

    matching_ids = [
        int(concept_id)
        for concept_id, name in candidates
        if name == "Systolic blood pressure"
    ]
    assert matching_ids == [3004249, 4152194]
