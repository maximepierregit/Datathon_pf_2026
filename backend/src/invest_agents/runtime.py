"""Réglages d'exécution du backend (Bedrock, pipeline d'agents), lus dans les variables d'environnement.

Les réglages financiers (données, rendements, covariance, contraintes) sont dans `config.py`.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from functools import lru_cache


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RuntimeSettings:
    region: str
    model_strong: str
    model_fast: str
    effort: str
    max_tokens: int
    thinking: bool
    max_pm_retries: int
    max_assets_per_portfolio: int


# Tous les agents tournent sous Claude Opus 5.5, effort de réflexion « high » (le défaut d'Opus 5.5 est « medium »).
DEFAULT_MODEL = "global.anthropic.claude-opus-5-5"


@lru_cache(maxsize=1)
def get_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings(
        region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
        model_strong=os.getenv("MODEL_STRONG", DEFAULT_MODEL),
        model_fast=os.getenv("MODEL_FAST", DEFAULT_MODEL),
        effort=os.getenv("MODEL_EFFORT", "high"),
        # La réflexion compte dans max_tokens: à effort élevé, 8000 tronque les réponses structurées.
        max_tokens=int(os.getenv("MODEL_MAX_TOKENS", "16000")),
        thinking=_bool("ENABLE_THINKING", True),
        max_pm_retries=int(os.getenv("MAX_PM_RETRIES", "1")),
        max_assets_per_portfolio=int(os.getenv("MAX_ASSETS_PER_PORTFOLIO", "40")),
    )
