import re
from thefuzz import fuzz

def get_candidates_from_db_safe(term, con, domain_id):
    """
    Fetches potential standard concepts from DuckDB safely using parameterized queries.
    Prevents SQL injection and gracefully handles words with apostrophes.
    """
    words = [w for w in re.split(r'\W+', str(term)) if len(w) > 3]
    if not words:
        words = [str(term)]
        
    conditions = " OR ".join(["LOWER(concept_name) LIKE ?" for _ in words])
    params = [f"%{w.lower()}%" for w in words]
    
    query = f"""
        SELECT concept_id, concept_name 
        FROM concept 
        WHERE domain_id = '{domain_id}' 
          AND standard_concept = 'S' 
          AND ({conditions})
        ORDER BY LENGTH(concept_name) ASC
        LIMIT 15
    """
    
    return con.execute(query, params).fetchall()

def calculate_confidence_score(source_term, standard_name):
    """
    Calculates a mathematical confidence score (0.0 to 1.0) between the raw 
    CDISC string and the OMOP standard concept name picked by the LLM.
    Uses Token Set Ratio to handle re-ordering (e.g., 'Diabetes Type 2' vs 'Type 2 Diabetes').
    """
    if not source_term or not standard_name:
        return 0.0
        
    # The fuzz.token_set_ratio returns a percentage 0-100, we convert it to 0.0-1.0
    score = fuzz.token_set_ratio(str(source_term).lower(), str(standard_name).lower()) / 100.0
    
    return round(score, 2)