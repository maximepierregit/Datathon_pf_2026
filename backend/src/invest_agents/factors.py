"""Scores de facteurs des actions (`data-prep/factors_model.ipynb`, voir `data-prep/FACTORS.md`).

Code pur, sans LLM. Chaque action détenue en direct a 5 z-scores calculés dans sa cellule (marché de cotation ×
secteur GICS): 0 = moyenne de la cellule, +1 = un écart-type mieux. Les FNB et les cryptos n'ont pas de score.

L'exposition d'un portefeuille à un facteur est la moyenne de ces scores pondérée par les poids, sur les seules
actions détenues en direct: b = Σ wᵢ·zᵢ / Σ wᵢ. Elle est linéaire une fois réécrite Σ wᵢ·(zᵢ − seuil) ≥ 0, ce qui
permet à l'optimiseur de l'imposer (`catalog.plan_for`).

Source: `MONPORT_FACTORS_PARQUET_URI` (local ou s3://bucket/key), sinon `data/factor_scores.parquet`. Une source
absente donne une table vide: les préférences de facteurs sont alors ignorées, sans plantage.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Mapping, Optional

import pandas as pd

from .data import load_market_data

logger = logging.getLogger(__name__)

FACTORS_ENV_VAR = "MONPORT_FACTORS_PARQUET_URI"
DEFAULT_FACTORS_PATH = Path(__file__).resolve().parents[2] / "data" / "factor_scores.parquet"

# Facteurs du moteur. `small_cap` est le score de taille inversé: dans les données, une grande entreprise a un score
# de taille positif, alors que le client demande des petites capitalisations.
FACTORS = ("momentum", "quality", "value", "growth", "small_cap")
FACTOR_FR = {"momentum": "momentum", "quality": "qualité", "value": "valeur", "growth": "croissance",
             "small_cap": "petites capitalisations"}
RAW_COLUMNS = ("ticker", "momentum", "quality", "value", "growth", "size")


def get_factors_source() -> str:
    return os.getenv(FACTORS_ENV_VAR, "").strip() or str(DEFAULT_FACTORS_PATH)


def prepare_scores(frame: pd.DataFrame) -> pd.DataFrame:
    """Index = symbole (en majuscules), une colonne par facteur du moteur."""
    missing = [c for c in RAW_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"Scores de facteurs incomplets, colonnes absentes: {missing}")
    df = frame.loc[:, list(RAW_COLUMNS)].copy()
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df = df.drop_duplicates("ticker").set_index("ticker")
    df["small_cap"] = -df.pop("size")
    return df.astype(float).fillna(0.0).loc[:, list(FACTORS)]


_lock = threading.Lock()
_cache: Optional[pd.DataFrame] = None


def get_scores() -> pd.DataFrame:
    """Table chargée une seule fois. Vide si la source est absente ou illisible."""
    global _cache
    with _lock:
        if _cache is None:
            source = get_factors_source()
            try:
                if not source.startswith("s3://") and not Path(source).is_file():
                    raise FileNotFoundError(f"Scores de facteurs introuvables: {source}. Définir {FACTORS_ENV_VAR}.")
                _cache = prepare_scores(load_market_data(source))
                logger.info("Scores de facteurs chargés: %d actions (%s)", len(_cache), source)
            except Exception as exc:  # noqa: BLE001  (S3 inaccessible, fichier absent...)
                logger.warning("Préférences de facteurs ignorées: %s", exc)
                _cache = pd.DataFrame(columns=list(FACTORS), dtype=float)
        return _cache


def scores_for(symbols) -> pd.DataFrame:
    """Scores des symboles qui en ont (actions détenues en direct présentes dans la table)."""
    table = get_scores()
    return table.loc[table.index.intersection(pd.Index(list(symbols)))]


def available_factors(symbols) -> list[str]:
    """Facteurs utilisables dans cet univers: au moins une action notée."""
    return list(FACTORS) if not scores_for(symbols).empty else []


def meets(scores: pd.DataFrame, thresholds: list[tuple[str, bool, float]]) -> list[str]:
    """Actions qui respectent chaque seuil à elles seules: (facteur, True = minimum / False = maximum, seuil).
    Un portefeuille de ces actions respecte donc toutes les contraintes, quels que soient les poids."""
    mask = pd.Series(True, index=scores.index)
    for factor, is_min, threshold in thresholds:
        mask &= scores[factor] >= threshold if is_min else scores[factor] <= threshold
    return scores.index[mask].tolist()


def exposure(weights: Mapping[str, float], factor: str) -> tuple[Optional[float], float]:
    """(exposition b du facteur, part du portefeuille couverte par des actions notées). b = None sans action notée."""
    scored = scores_for(weights.keys())
    covered = sum(float(weights[s]) for s in scored.index)
    if covered <= 0:
        return None, 0.0
    total = sum(float(weights[s]) * float(scored.at[s, factor]) for s in scored.index)
    return total / covered, covered


def exposures(weights: Mapping[str, float]) -> tuple[dict[str, float], float]:
    """Exposition à chaque facteur et couverture. Dictionnaire vide sans action notée."""
    out, covered = {}, 0.0
    for f in FACTORS:
        b, covered = exposure(weights, f)
        if b is not None:
            out[f] = round(b, 3)
    return out, round(covered, 4)


__all__ = ["FACTORS", "FACTOR_FR", "available_factors", "exposure", "exposures", "get_scores", "scores_for"]
