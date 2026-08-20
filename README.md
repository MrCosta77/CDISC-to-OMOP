# 🏥 CDISC to OMOP Common Data Model (CDM) Pipeline

![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)
![DuckDB](https://img.shields.io/badge/DuckDB-Relational-yellow.svg)
![AI/RAG](https://img.shields.io/badge/AI_Mapping-Qwen2.5%20%7C%20Ollama-orange.svg)
![Tests](https://img.shields.io/badge/pytest-Passing-brightgreen.svg)
![OMOP](https://img.shields.io/badge/OMOP_CDM-v5.4-blueviolet.svg)

A production-ready, end-to-end clinical data engineering pipeline demonstrating the transformation of clinical trial data from the **CDISC standard (SDTM/ADaM)** into the **OMOP Common Data Model (CDM) v5.4**, bridging the gap between isolated clinical research and global Real-World Evidence (RWE).

## 🚀 Core Architecture & Engineering Highlights

* **Hybrid Semantic Mapping with Guardrails:** Combines high-performance deterministic string matching (using official OHDSI `Maps To` relationships) with a local AI Agent (RAG via Ollama). 
* **Regulatory-Grade Auditability:** Every AI or deterministic mapping decision is logged into a custom `mapping_provenance` table. AI mappings are mathematically scored using Token Set Ratio (FuzzyWuzzy/Jaro-Winkler) and flagged as `Pending_Human_Review` to ensure Human-in-the-Loop governance.
* **Clinical Time Rigor:** Derives unbiased `OBSERVATION_PERIOD` spans using strict CDISC Demographics reference dates (`RFSTDTC`/`RFENDTC`), preventing longitudinal biases from past medical history events.
* **Software Engineering Best Practices:**
  * Parameterized SQL queries to prevent SQL injection.
  * Comprehensive `.env` configuration management.
  * Automated `pytest` suites ensuring mathematical determinism and collision resistance for 64-bit ID generation.
  * Standardized `logger` writing synchronized, timestamped execution trails to `logs/pipeline.log`.
* **Unified SQL Engine:** Ingests all normalized tables into a high-performance **DuckDB** relational database, ensuring data integrity and immediate readiness for OHDSI analytical tools (like Achilles or DQD).

## 📂 Repository Structure

* `data/raw/`: Input `.sas7bdat` clinical trial files (ignored by git).
* `data/processed/`: Normalized OMOP CSV tables generated during transformation.
* `src/etl/`: Core transformation scripts (`person`, `condition`, `drug`, `measurement`, `observation_period`, `visit`, `link_visits`, `build_database`).
* `src/mapping/`: 
  * `deterministic_mapping.py`: OHDSI vocabulary exact matchers.
  * `llm_shared.py`: Parameterized SQL retrieval and mathematical confidence scoring.
  * `llm_*.py`: AI semantic agents for distinct clinical domains.
* `src/analytics/`: RWE analytical scripts (`rwe_queries.py`).
* `src/utils/`: Configuration (`config.py`), central algorithms (`helpers.py`), audit setup (`setup_audit.py`), and standardized logging (`logger.py`).
* `tests/`: Pytest suites verifying core data engineering functions.
* `main.py`: Fully idempotent orchestrator.

## 🛠️ Pipeline Execution Flow

1. **Phase 1: Vocabularies & Audit Setup** — Initializes OHDSI standard concepts inside DuckDB and builds the `mapping_provenance` and `cdm_source` metadata tables.
2. **Phase 2: Structural ETL** — Transforms raw CDISC domains (DM, AE, MH, EX, CM, LB, VS, EG) into OMOP clinical tables, calculates observation spans, derives visits, and links foreign keys.
3. **Phase 3: Semantic Mapping** — Applies exact string matching followed by AI-driven semantic disambiguation for orphan records. If the AI confidence score falls below the `CONFIDENCE_THRESHOLD`, the mapping is safely rejected.
4. **Phase 4: Database Build** — Packs all processed datasets into a unified `cdisc_omop.duckdb` relational file.

## ⚙️ How to Reproduce

**1. Clone the repository:**
```bash
git clone https://github.com/MrCosta77/CDISC-to-OMOP
cd CDISC-to-OMOP
```

**2. Install dependencies:**
```bash
pip install -r requirements.txt
```

**3. Configure the Environment:**
Copy the example environment file and adjust if necessary (e.g., select your local LLM model and confidence threshold).
```bash
cp .env.example .env
```

**4. Run Unit Tests (Optional but recommended):**
Ensure the mathematical core is intact before running the ETL.
```bash
pytest -v
```

**5. Place your raw data:**
Ensure your source `.sas7bdat` files and OHDSI vocabularies are inside the `data/raw/` and `data/omop_vocab/` directories, respectively.

**6. Run the full automated orchestrator:**
```bash
python main.py
```
*(Track the execution in real-time or check `logs/pipeline.log` for the detailed audit trail).*

**7. Run RWE Analytics:**
Generate cohort demographics, adverse event frequencies, and rescue medication phenotyping.
```bash
python src/analytics/rwe_queries.py
```