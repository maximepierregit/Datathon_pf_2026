"""Mandats des trois gestionnaires de portefeuille.

Les trois PM reçoivent le même profil et les mêmes contraintes. Ils diffèrent par leur objectif
d'optimisation et leur style de sélection. Modifier cette liste pour changer leur différenciation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .allocator import Objective


@dataclass(frozen=True)
class Mandate:
    id: str
    name: str
    objective: Objective
    description: str
    guidance: str
    vol_cap_factor: Optional[float]  # fraction de la volatilité maximale du profil; None = pas de plafond propre
    risk_aversion: Optional[float] = None  # coefficient A de l'objectif mean_variance


MANDATES: list[Mandate] = [
    Mandate(
        id="pm1",
        name="Défensif",
        objective="min_volatility",
        description="Minimise la volatilité sous les contraintes. Priorité à la préservation du capital.",
        guidance=(
            "Choisis des actifs à faible volatilité et à faible corrélation entre eux: titres défensifs, "
            "ETF diversifiés, secteurs stables. Évite les actifs très volatils (crypto incluse) sauf si une "
            "contrainte l'exige."
        ),
        vol_cap_factor=None,
    ),
    Mandate(
        id="pm2",
        name="Équilibré",
        objective="max_sharpe",
        description="Maximise le rendement ajusté du risque (ratio de Sharpe historique) sous les contraintes.",
        guidance=(
            "Cherche le meilleur compromis rendement/risque. Diversifie sur plusieurs secteurs, pays et classes "
            "d'actifs, avec des actifs au Sharpe élevé."
        ),
        vol_cap_factor=0.85,
    ),
    Mandate(
        id="pm3",
        name="Croissance",
        objective="max_return",
        description="Maximise le rendement historique sous la volatilité maximale du profil et les contraintes.",
        guidance=(
            "Privilégie les actifs au rendement historique élevé, tout en gardant assez de diversification pour "
            "que la volatilité reste sous le plafond du profil. Ne concentre pas le portefeuille."
        ),
        vol_cap_factor=1.0,
    ),
]


def vol_cap_for(mandate: Mandate, suggested_max_volatility: float) -> Optional[float]:
    if mandate.vol_cap_factor is None:
        return None
    return suggested_max_volatility * mandate.vol_cap_factor
