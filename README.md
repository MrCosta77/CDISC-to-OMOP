# 🏥 CDISC to OMOP Common Data Model (CDM) Pipeline

![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)
![DuckDB](https://img.shields.io/badge/DuckDB-Relational-yellow.svg)
![AI/RAG](https://img.shields.io/badge/AI_Mapping-Qwen2.5%20%7C%20Ollama-orange.svg)
![Tests](https://img.shields.io/badge/pytest-Passing-brightgreen.svg)
![OMOP](https://img.shields.io/badge/OMOP_CDM-v5.4-blueviolet.svg)

An end-to-end clinical data engineering pipeline with production-oriented controls, demonstrating the transformation of clinical trial data from the **CDISC standard (SDTM/ADaM)** into the **OMOP Common Data Model (CDM) v5.4**, bridging the gap between isolated clinical research and global Real-World Evidence (RWE).

## 🚀 Core Architecture & Engineering Highlights

* **Hybrid Semantic Mapping with Guardrails:** Combines deterministic matching through official OHDSI `Maps To` relationships with local LLM candidate proposals. LLM proposals never update clinical tables directly.
* **Human Review Gate:** AI proposals are stored in `mapping_decision`, linked to affected events, and must be explicitly approved before entering `approved_mapping_set`. Only approved mappings are applied on a subsequent run and recorded in `mapping_provenance`.
* **Pinned OMOP Schema:** Installs all 39 tables from the OHDSI CDM v5.4.3 field specification. Populated tables use explicit DuckDB types, required fields, primary keys, staging tables, and relational acceptance checks.
* **Clinical Time Rigor:** Derives unbiased `OBSERVATION_PERIOD` spans using strict CDISC Demographics reference dates (`RFSTDTC`/`RFENDTC`), preventing longitudinal biases from past medical history events.
* **Software Engineering Best Practices:**
  * Parameterized SQL queries to prevent SQL injection.
  * Comprehensive `.env` configuration management.
  * Automated `pytest` suites ensuring mathematical determinism and collision resistance for 64-bit ID generation.
  * Standardized `logger` writing synchronized, timestamped execution trails to `logs/pipeline.log`.
* **Unified SQL Engine:** Publishes normalized tables transactionally into **DuckDB**, with a standalone structural and relational acceptance command.

## 📂 Repository Structure

* `data/raw/`: Input `.sas7bdat` clinical trial files (ignored by git).
* `data/processed/`: Normalized OMOP CSV tables generated during transformation.
* `resources/omop_cdm_v5_4/`: Pinned OHDSI v5.4.3 field specification, verified by SHA-256.
* `src/omop/`: DDL generation and schema-contract validation for DuckDB.
* `src/etl/`: Core transformation scripts (`person`, `condition`, `drug`, `measurement`, `observation_period`, `visit`, `link_visits`, `build_database`).
* `src/mapping/`: 
  * `deterministic_mapping.py`: OHDSI vocabulary exact matchers.
  * `llm_shared.py`: Parameterized SQL retrieval and mathematical confidence scoring.
  * `llm_*.py`: AI semantic agents for distinct clinical domains.
* `src/analytics/`: RWE analytical scripts (`rwe_queries.py`).
* `src/quality/`: Standalone acceptance checks for the published CDM.
* `src/utils/`: Configuration (`config.py`), central algorithms (`helpers.py`), audit setup (`setup_audit.py`), and standardized logging (`logger.py`).
* `tests/`: Pytest suites verifying core data engineering functions.
* `main.py`: Idempotent orchestrator with a unique `run_id` and run-level audit trail.

## 🛠️ Pipeline Execution Flow

1. **Phase 1: Schema, Vocabularies & Audit Setup** — Installs the pinned 39-table OMOP CDM v5.4.3 contract, loads typed vocabularies, and builds audit metadata.
2. **Phase 2: Structural ETL** — Transforms raw CDISC domains (DM, AE, MH, EX, CM, LB, VS, EG) into OMOP clinical tables, calculates observation spans, derives visits, and links foreign keys.
3. **Phase 3: Semantic Mapping** — Applies deterministic mappings and previously approved human mappings. The LLM only proposes candidates for the remaining orphan terms; pending proposals stay as concept ID `0` in the published clinical tables.
4. **Phase 4: Validated Publication** — Loads CSV outputs into temporary staging tables, casts them into the official contract, validates required fields, keys, dates, concepts and relations, then atomically publishes `cdisc_omop.duckdb`.

## ⚙️ How to Reproduce

**1. Clone the repository:**
```bash
git clone https://github.com/MrCosta77/CDISC-to-OMOP
cd CDISC-to-OMOP
```

**2. Create an isolated environment and install dependencies (Windows PowerShell):**
```bash
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

**3. Configure the Environment:**
Copy the example environment file and adjust if necessary (e.g., select your local LLM model and confidence threshold).
```bash
Copy-Item .env.example .env
```

**4. Run Unit Tests (Optional but recommended):**
Ensure the mathematical core is intact before running the ETL.
```bash
.\.venv\Scripts\python -m pytest -v
```

**5. Place your raw data:**
Ensure your source `.sas7bdat` files and OHDSI vocabularies are inside the `data/raw/` and `data/omop_vocab/` directories, respectively.

**6. Run the full automated orchestrator:**
```bash
.\.venv\Scripts\python main.py
```
Each execution receives a unique `run_id`. Its status, input manifest, Git commit,
configuration snapshot, output counts, error (if any), and mapping provenance are
stored in DuckDB. Track execution in real time or inspect `logs/pipeline.log`.

**7. Validate the published OMOP CDM:**
```powershell
.\.venv\Scripts\python -m src.quality.validate_cdm
```

**8. Review LLM proposals:**
```bash
.\.venv\Scripts\python -m src.mapping.review_mappings list --run-id latest
```
Inspect all active reusable approval and rejection rules:
```powershell
.\.venv\Scripts\python -m src.mapping.review_mappings rules
```
Approve a proposal (optionally replacing the proposed Concept ID):
```powershell
.\.venv\Scripts\python -m src.mapping.review_mappings approve 1 --reviewer "Reviewer Name" --reason "Validated against the Standard Vocabulary" --concept-id 201826
```
Or reject it:
```powershell
.\.venv\Scripts\python -m src.mapping.review_mappings reject 1 --reviewer "Reviewer Name" --reason "Candidate adds unsupported clinical specificity"
```
Run `main.py` again after review. The next run applies only the active mappings in
`approved_mapping_set`.

**9. Run RWE Analytics:**
Generate cohort demographics, adverse event frequencies, and rescue medication phenotyping.
```bash
python src/analytics/rwe_queries.py
```

## OMOP Schema Provenance

The schema metadata is pinned to the official
[OHDSI CommonDataModel v5.4.3 release](https://github.com/OHDSI/CommonDataModel/releases/tag/v5.4.3),
commit `746a15e0fb36a95ba6cc0993737f1273bbad92f2`. The vendored field
specification is the OHDSI source of truth used to generate the DDL and is
verified at runtime with SHA-256
`2b763c7a2aeb309372c1564350939551531318e2078fd4443e03b2741e79b77c`.
Logical OMOP `integer` fields are represented as DuckDB `BIGINT` so generated
64-bit identifiers remain valid.
