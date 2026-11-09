"""Project configuration, read from environment variables (and a local .env file)."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# src/regintel/config.py -> parents[2] is the repo root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

OPENFDA_API_KEY = os.getenv("OPENFDA_API_KEY")  # optional; raises openFDA rate limits
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")


def get_database_url() -> str:
    """Use DATABASE_URL if set (e.g. Postgres in deployment), else a local SQLite file."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    DATA_DIR.mkdir(exist_ok=True)
    return f"sqlite:///{DATA_DIR / 'regintel.db'}"
