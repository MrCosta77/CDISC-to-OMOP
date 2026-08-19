import os
from pathlib import Path
from dotenv import load_dotenv

# Automatically load environment variables from the .env file
load_dotenv()

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Fetch configurations from .env, with safe fallbacks
DB_PATH = os.getenv("DB_PATH", str(PROJECT_ROOT / "data" / "cdisc_omop.duckdb"))
MODEL_NAME = os.getenv("MODEL_NAME", "qwen2.5-coder:7b")
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.90"))
VOCAB_DIR = os.getenv("VOCAB_DIR", str(PROJECT_ROOT / "data" / "omop_vocab"))
