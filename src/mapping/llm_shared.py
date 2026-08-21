import re
from thefuzz import fuzz


GENERIC_CLINICAL_TOKENS = {
    "duration",
    "level",
    "measurement",
    "result",
    "site",
    "test",
    "type",
}


def _clinical_tokens(term):
    # Preserve common two-letter ECG abbreviations such as QT and RR, including
    # vocabulary spellings such as Q-T and R-R.
    normalized = re.sub(
        r"\b([a-zA-Z])[-\s]([a-zA-Z])\b",
        lambda match: "".join(match.groups()),
        str(term),
    ).lower()
    return [
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if len(token) >= 2 or token.isdigit()
    ]


def _candidate_rank(source_term, candidate_name):
    source_tokens = set(_clinical_tokens(source_term))
    candidate_tokens = set(_clinical_tokens(candidate_name))
    informative = source_tokens.difference(GENERIC_CLINICAL_TOKENS) or source_tokens
    informative_overlap = len(informative.intersection(candidate_tokens)) / max(
        len(informative), 1
    )
    total_overlap = len(source_tokens.intersection(candidate_tokens)) / max(
        len(source_tokens), 1
    )
    fuzzy_score = fuzz.token_sort_ratio(
        str(source_term).lower(), str(candidate_name).lower()
    )
    return informative_overlap, total_overlap, fuzzy_score, -len(str(candidate_name))


def get_candidates_from_db_safe(term, con, domain_id):
    """
    Fetches potential standard concepts from DuckDB safely using parameterized queries.
    Prevents SQL injection and gracefully handles words with apostrophes.
    """
    words = _clinical_tokens(term)
    if not words:
        words = [str(term)]
    informative_words = [
        word for word in words if word not in GENERIC_CLINICAL_TOKENS
    ] or words
    primary_word = max(informative_words, key=len)

    conditions = " OR ".join(
        [
            "(LOWER(concept_name) LIKE ? OR "
            "REGEXP_REPLACE(LOWER(concept_name), '[^a-z0-9]', '', 'g') LIKE ?)"
            for _ in words
        ]
    )
    
    # PARAMETRIZAÇÃO TOTAL: O domain_id é agora o primeiro parâmetro seguro
    query = f"""
        SELECT concept_id, concept_name
        FROM concept
        WHERE domain_id = ?
          AND standard_concept = 'S'
          AND (invalid_reason IS NULL OR invalid_reason = '')
          AND ({conditions})
        ORDER BY
          CASE WHEN REGEXP_REPLACE(
              LOWER(concept_name), '[^a-z0-9]', '', 'g'
          ) LIKE ? THEN 0 ELSE 1 END,
          LENGTH(concept_name)
        LIMIT 1000
    """

    params = []
    for word in words:
        params.extend((f"%{word.lower()}%", f"%{word.lower()}%"))
    params.append(f"%{primary_word.lower()}%")
    full_params = [domain_id] + params

    candidates = con.execute(query, full_params).fetchall()
    return sorted(
        candidates,
        key=lambda row: _candidate_rank(term, row[1]),
        reverse=True,
    )[:15]

def calculate_confidence_score(source_term, standard_name):
    """
    Calculates a mathematical confidence score (0.0 to 1.0) between the raw 
    CDISC string and the OMOP standard concept name picked by the LLM.
    """
    if not source_term or not standard_name:
        return 0.0
        
    score = fuzz.token_set_ratio(str(source_term).lower(), str(standard_name).lower()) / 100.0
    return round(score, 2)
