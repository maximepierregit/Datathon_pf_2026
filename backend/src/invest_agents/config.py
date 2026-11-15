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
    thinking: bool
    dataset_path: str
    max_pm_retries: int
    max_assets_per_portfolio: int
    risk_free_rate: float
    mu_shrink: float


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
        model_strong=os.getenv("MODEL_STRONG", "global.anthropic.claude-sonnet-5-5"),
        model_fast=os.getenv("MODEL_FAST", "global.anthropic.claude-haiku-5-5"),
        thinking=_bool("ENABLE_THINKING", True),
        dataset_path=os.getenv("DATASET_PATH", str(BACKEND_ROOT / "data" / "universe.parquet")),
        max_pm_retries=int(os.getenv("MAX_PM_RETRIES", "1")),
        max_assets_per_portfolio=int(os.getenv("MAX_ASSETS_PER_PORTFOLIO", "40")),
        risk_free_rate=float(os.getenv("RISK_FREE_RATE", "0.025")),  # même valeur que le frontend
        mu_shrink=float(os.getenv("MU_SHRINK", "0.5")),
    )
