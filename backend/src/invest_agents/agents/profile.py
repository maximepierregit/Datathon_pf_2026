"""Agent Profil (étape 4): évalue le profil de risque à partir du formulaire structuré."""

from __future__ import annotations

import json

from ..catalog import describe
from ..events import EventBus
from ..schemas import Constraint, ConstraintType as T, InvestorForm, InvestorProfile, ProfileAssessment
from .base import run_agent

SYSTEM = """Tu es l'agent Profil d'un service de conseil en placement canadien (montants en CAD).
Tu reçois le formulaire structuré d'un investisseur et les contraintes déjà retenues. Tu évalues son profil de
risque. Tu ne construis aucun portefeuille.

Repères pour la volatilité annualisée maximale suggérée:
- conservateur: 5 à 8 %; modéré: 8 à 11 %; équilibré: 11 à 14 %; dynamique: 14 à 18 %; agressif: 18 à 25 %.
- Si une perte annuelle maximale acceptée est déclarée, la volatilité suggérée ne dépasse pas environ la moitié
  de cette perte (deux écarts-types).
- Un horizon court (moins de 3 ans) ou des besoins de liquidité élevés réduisent la tolérance réelle.

Repère pour le poids maximal par titre: 5 à 10 % pour un profil prudent, 10 à 15 % pour un profil équilibré,
15 à 25 % pour un profil agressif.

Dans `flags`, note les tensions visibles dans le formulaire (ex.: objectif de croissance agressive avec un horizon
de 2 ans, ou une tolérance déclarée très élevée avec une perte acceptée très faible). N'invente aucune donnée absente."""


# Contraintes par défaut dérivées du profil: des préférences, que l'optimiseur peut promouvoir en contraintes dures
# lorsqu'elles ne contredisent pas celles de l'utilisateur.
def assemble_profile(form: InvestorForm, user_constraints: list[Constraint], assessment: ProfileAssessment) -> InvestorProfile:
    types = {c.type for c in user_constraints if c.hard}
    constraints = list(user_constraints)
    if T.MAX_VOLATILITY not in types:
        constraints.append(
            Constraint(type=T.MAX_VOLATILITY, value=assessment.suggested_max_volatility, hard=False,
                       source="profile", note="Volatilité maximale suggérée par le profil")
        )
    if T.MAX_POSITION_WEIGHT not in types:
        constraints.append(
            Constraint(type=T.MAX_POSITION_WEIGHT, value=assessment.suggested_max_position_weight, hard=False,
                       source="profile", note="Poids maximal par titre suggéré par le profil")
        )
    return InvestorProfile(form=form, assessment=assessment, constraints=constraints)


async def run_profile_agent(bus: EventBus, form: InvestorForm, constraints: list[Constraint]) -> ProfileAssessment:
    payload = {
        "formulaire": form.model_dump(mode="json", exclude={"constraints"}),
        "contraintes_retenues": [describe(c) for c in constraints],
    }
    return await run_agent(
        bus=bus,
        label="Profil",
        step="4",
        kind="fast",
        system_prompt=SYSTEM,
        user_prompt="Évalue ce profil d'investisseur.\n\n" + json.dumps(payload, ensure_ascii=False, indent=2),
        schema=ProfileAssessment,
        start_text="Analyse du profil d'investisseur",
        done_text="Profil établi",
    )
