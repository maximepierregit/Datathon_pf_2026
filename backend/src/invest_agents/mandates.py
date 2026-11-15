"""Mandats des trois portefeuilles, alignés sur le frontend (`PORTFOLIO_META` dans lib/engine.ts).

- Prudent: le profil passe avant les préférences.
- Équilibré: le juste milieu, affiché par défaut.
- Conviction: les préférences passent avant le profil, dans les limites de sécurité.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .optimizer import Objective


@dataclass(frozen=True)
class Mandate:
    id: str  # PortfolioId du frontend
    name: str
    tagline: str
    objective: Objective
    description: str
    guidance: str
    vol_cap_factor: Optional[float]  # fraction de la volatilité maximale du profil; None = pas de plafond propre
    score_shift: int  # décalage du score de risque, comme `classWeights` dans engine.ts


MANDATES: list[Mandate] = [
    Mandate(
        id="prudent",
        name="Prudent",
        tagline="Ton profil d’abord : on privilégie la stabilité, quitte à mettre de côté certaines préférences.",
        objective="min_volatility",
        description="Minimise la volatilité dans la répartition prudente. Le profil passe avant les préférences.",
        guidance=(
            "Choisis des placements stables et peu corrélés entre eux: FNB obligataires, FNB diversifiés, "
            "titres défensifs. Évite les placements très volatils (crypto incluse) sauf si une contrainte l'exige."
        ),
        vol_cap_factor=None,
        score_shift=-20,
    ),
    Mandate(
        id="equilibre",
        name="Équilibré",
        tagline="Le juste milieu entre ton profil et tes préférences. Un bon point de départ.",
        objective="max_sharpe",
        description="Maximise le rendement ajusté du risque, sous la volatilité maximale du profil.",
        guidance=(
            "Cherche le meilleur compromis rendement/risque. Diversifie entre classes d'actifs, régions et "
            "placements au Sharpe élevé."
        ),
        vol_cap_factor=1.0,
        score_shift=0,
    ),
    Mandate(
        id="conviction",
        name="Conviction",
        tagline="Tes préférences d’abord : on suit tes choix, dans les limites de sécurité.",
        objective="max_return",
        description="Maximise le rendement en suivant les préférences, sous un plafond de volatilité élargi.",
        guidance=(
            "Suis les préférences du client en priorité. Privilégie les placements au rendement élevé, tout en "
            "gardant assez de diversification pour rester sous le plafond de volatilité. Ne concentre pas le portefeuille."
        ),
        vol_cap_factor=1.3,
        score_shift=10,
    ),
]

MANDATE_BY_ID = {m.id: m for m in MANDATES}


def vol_cap_for(mandate: Mandate, suggested_max_volatility: float) -> Optional[float]:
    if mandate.vol_cap_factor is None:
        return None
    return suggested_max_volatility * mandate.vol_cap_factor
