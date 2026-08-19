import os
from pathlib import Path

# Get the absolute path of the project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Centralized Paths
DB_PATH = os.path.join(PROJECT_ROOT, "data", "cdisc_omop.duckdb")
VOCAB_DIR = os.path.join(PROJECT_ROOT, "data", "omop_vocab")

# LLM Configurations
MODEL_NAME = "qwen2.5-coder:7b"