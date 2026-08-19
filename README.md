# 🏥 CDISC to OMOP Common Data Model (CDM) Pipeline

An end-to-end clinical data engineering pipeline demonstrating the transformation of clinical trial data from the **CDISC standard (SDTM/ADaM)** into the **OMOP Common Data Model (CDM)**, bridging the gap between clinical research and Real-World Evidence (RWE).

## 🚀 Core Architecture & Engineering Highlights
* **Hybrid Semantic Mapping:** Combines high-performance deterministic string matching against official OHDSI vocabularies (SNOMED, RxNorm) with a local AI Agent (RAG via Ollama/Qwen) to resolve orphan clinical concepts safely.
* **Longitudinal Aggregation:** Automatically derives patient observation timelines (`OBSERVATION_PERIOD`) and clinical encounters (`VISIT_OCCURRENCE`) from disparate event dates.
* **Unified SQL Engine:** Ingests processed tables into a high-performance **DuckDB** relational database, ensuring data integrity and readiness for OHDSI analytical tools.
* **Centralized Orchestration:** Driven by a robust, idempotent `main.py` script that executes the entire ETL, mapping, and database construction pipeline sequentially.

## 📂 Repository Structure
* `data/raw/`: Place your input `.sas7bdat` clinical trial files here (ignored by git).
* `data/processed/`: Normalized OMOP CSV tables generated during transformation.
* `src/etl/`: Core transformation scripts (`person.py`, `condition.py`, `drug.py`, `measurement.py`, `observation_period.py`, `visit.py`, `link_visits.py`, `build_database.py`).
* `src/mapping/`: Deterministic matchers and local LLM semantic agents (`llm_condition.py`, `llm_drug.py`).
* `src/analytics/`: RWE analytical scripts (`rwe_queries.py`).
* `src/utils/`: Configuration management (`config.py`) and helper routines (`helpers.py`, `setup_vocab.py`).
* `main.py`: Full pipeline orchestrator.

## 🛠️ Pipeline Execution Flow

1. **Phase 1: Vocabularies Setup** — Initializes OHDSI standard concepts insideDuckDB.
2. **Phase 2: Structural ETL** — Transforms raw CDISC domains (DM, AE, MH, EX, CM, LB, VS, EG) into OMOP clinical tables, calculates observation spans, derives visits, and links foreign keys.
3. **Phase 3: Semantic Mapping** — Applies exact string matching followed by AI-driven semantic disambiguation for unmapped orphan records.
4. **Phase 4: Database Build** — Packs all processed datasets into a unified `cdisc_omop.duckdb` relational file.

## ⚙️ How to Reproduce

1. **Clone the repository:**
   `git clone https://github.com/MrCosta77/CDISC-to-OMOP.git`

2. **Install dependencies:**
   `pip install -r requirements.txt`

3. **Place your raw data:**
   Ensure your `.sas7bdat` files are inside the `data/raw/` directory.

4. **Run the full automated pipeline:**
   `python main.py`

5. **Run RWE Analytics:**
   `python src/analytics/rwe_queries.py`