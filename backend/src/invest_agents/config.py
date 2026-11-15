"""Configuration lue depuis les variables d'environnement."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    region: str
    model_strong: str
    model_fast: str
    effort: str
    max_tokens: int
    thinking: bool
    dataset_path: str
    max_pm_retries: int
    max_assets_per_portfolio: int
    risk_free_rate: float


# Tous les agents tournent sous Claude Opus 5.5, effort de réflexion « high » (le défaut d'Opus 5.5 est « medium »).
DEFAULT_MODEL = "global.anthropic.claude-opus-5-5"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
        model_strong=os.getenv("MODEL_STRONG", DEFAULT_MODEL),
        model_fast=os.getenv("MODEL_FAST", DEFAULT_MODEL),
        effort=os.getenv("MODEL_EFFORT", "high"),
        # La réflexion compte dans max_tokens: à effort élevé, 8000 tronque les réponses structurées.
        max_tokens=int(os.getenv("MODEL_MAX_TOKENS", "16000")),
        thinking=_bool("ENABLE_THINKING", True),
        dataset_path=os.getenv("DATASET_PATH", str(BACKEND_ROOT / "data" / "universe.parquet")),
        max_pm_retries=int(os.getenv("MAX_PM_RETRIES", "1")),
        max_assets_per_portfolio=int(os.getenv("MAX_ASSETS_PER_PORTFOLIO", "40")),
        risk_free_rate=float(os.getenv("RISK_FREE_RATE", "0.02")),
    )
