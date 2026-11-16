"""Projection sur 10 ans d'un portefeuille avec les ajouts prévus du client. Code pur, sans LLM.

Rendement moyen: le rendement annuel attendu μ (celui de l'optimiseur) est divisé par le nombre de versements par année
(26, 12 ou 1), composé à chaque période, puis le versement est ajouté:  valeur ← valeur × (1 + μ/n) + versement.
Sans ajouts (« aucune »), le capital de départ se compose seul, sur 12 périodes par année.

Fourchettes (les « cônes »): `PATHS` trajectoires simulées, graine fixe pour que le résultat soit reproductible. À chaque
période, le rendement d'une trajectoire est tiré d'une loi normale de moyenne μ/n et d'écart-type σ/√n; le cône probable
est le 25e–75e centile des trajectoires (environ ±0,67 écart-type), le cône large le 5e–95e (environ ±1,645).
Le cône est centré sur le rendement attendu: un rendement plus élevé le déplace, une volatilité plus élevée l'élargit.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

# Mêmes identifiants que ContributionFrequency (frontend/src/types.ts).
PER_YEAR = {"deux-semaines": 26, "mensuelle": 12, "annuelle": 1, "aucune": 12}
PATHS = 1000
SEED = 7
MAX_AMOUNT = 10_000_000.0


def clean_contribution(raw: Any) -> dict:
    """Les ajouts prévus reçus du client, validés. Tout ce qui est invalide devient « aucun ajout »."""
    if isinstance(raw, dict) and raw.get("frequency") in PER_YEAR and raw.get("frequency") != "aucune":
        try:
            amount = float(raw.get("amount"))
        except (TypeError, ValueError):
            amount = 0.0
        if 0 < amount <= MAX_AMOUNT:
            return {"frequency": raw["frequency"], "amount": round(amount, 2)}
    return {"frequency": "aucune", "amount": 0.0}


def project(start: float, contribution: Optional[dict], mu: float, sigma: float, years: int = 10,
            paths: int = PATHS, seed: int = SEED) -> list[dict]:
    """Une ligne par année (0 à `years`): rendement moyen (`expected`), montant versé (`invested`) et centiles
    5, 25, 75 et 95 des trajectoires simulées, en dollars."""
    c = clean_contribution(contribution)
    n = PER_YEAR[c["frequency"]]
    add = c["amount"]
    drift, spread = mu / n, sigma / np.sqrt(n)
    rng = np.random.default_rng(seed)
    value = np.full(paths, float(start))
    expected = invested = float(start)
    rows = [_row(0, expected, invested, value)]
    for year in range(1, years + 1):
        for _ in range(n):
            expected = expected * (1.0 + drift) + add
            invested += add
            value = value * (1.0 + drift + spread * rng.standard_normal(paths)) + add
        rows.append(_row(year, expected, invested, value))
    return rows


def projection_view(start: float, contribution: Optional[dict], mu: float, sigma: float, years: int = 10) -> dict:
    """La projection telle que le frontend l'affiche: les lignes par année, plus ce qui les explique (ajouts retenus,
    nombre de versements par année)."""
    c = clean_contribution(contribution)
    return {"contribution": c, "periodsPerYear": PER_YEAR[c["frequency"]], "rows": project(start, c, mu, sigma, years)}


def _row(year: int, expected: float, invested: float, paths: np.ndarray) -> dict:
    p05, p25, p75, p95 = np.percentile(paths, [5, 25, 75, 95])
    return {"year": year, "expected": round(expected, 2), "invested": round(invested, 2),
            "p05": round(float(p05), 2), "p25": round(float(p25), 2), "p75": round(float(p75), 2), "p95": round(float(p95), 2)}


__all__ = ["PER_YEAR", "clean_contribution", "project", "projection_view"]
