import os
from pathlib import Path
from dotenv import load_dotenv

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Load the project's environment even when a script is launched from elsewhere.
load_dotenv(PROJECT_ROOT / ".env")


def resolve_project_path(value):
    """Resolve relative configuration paths against the project root."""
    path = Path(value)
    return str(path if path.is_absolute() else PROJECT_ROOT / path)

# Fetch configurations from .env, with safe fallbacks
DB_PATH = resolve_project_path(
    os.getenv("DB_PATH", str(PROJECT_ROOT / "data" / "cdisc_omop.duckdb"))
)
MODEL_NAME = os.getenv("MODEL_NAME", "qwen2.5-coder:7b")
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.90"))
VOCAB_DIR = resolve_project_path(
    os.getenv("VOCAB_DIR", str(PROJECT_ROOT / "data" / "omop_vocab"))
)
