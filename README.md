# CDISC to OMOP Mapping Project

This repository contains the ETL (Extract, Transform, Load) pipelines to map clinical trial data from the CDISC standard (SDTM/ADaM) to the OMOP Common Data Model (CDM).

## Project Architecture
The project focuses on a structural and semantic translation from an event/study-centric model (CDISC) to a patient-centric longitudinal model (OMOP).

## Folder Structure
* `data/raw/`: Place your input `.sas7bdat` files here (ignored by git to protect sensitive data).
* `data/processed/`: The output OMOP `.csv` tables are saved here.
* `src/etl/`: Core transformation scripts (e.g., Demographics to `PERSON`).
* `src/mapping/`: AI-powered semantic mapping agents for dictionaries (MedDRA to SNOMED/RxNorm).
* `src/utils/`: Helper functions and configuration files.

## Setup Instructions
1. Install dependencies:
    pip install -r requirements.txt

2. Place your SDTM files (e.g., `dm.sas7bdat`) into the `data/raw/` directory.

3. Run the ETL pipeline:
    python src/etl/etl_person.py