"""Agent Juge (étape 8): un juge par portefeuille.

La conformité (`compliant`) est calculée par du code, pas par le modèle. Le modèle fournit l'avis
qualitatif (adéquation au profil, corrections suggérées).
"""

from __future__ import annotations

import json

from ..constraints import describe, evaluate
from ..data import Market
from ..events import EventBus
from ..schemas import Constraint, InvestorProfile, JudgeOpinion, JudgeVerdict, Portfolio
from ..tools import make_judge_tools
from .base import run_agent

SYSTEM = """Tu es l'agent Juge. Tu évalues UN portefeuille par rapport au profil et aux contraintes d'un investisseur.
1. Appelle d'abord `check_portfolio_constraints`. Ses résultats font foi: ne les contredis jamais.
2. Évalue l'adéquation globale au profil (score de 0 à 10): niveau de risque, diversification, cohérence avec l'objectif
   et l'horizon.
3. Si des contraintes ne sont pas respectées, propose des corrections concrètes dans `suggested_fixes`
   (ex.: « réduire le secteur Technologie à 25 % »). Sinon, laisse la liste vide."""


async def run_judge(
    bus: EventBus,
    market: Market,
    profile: InvestorProfile,
    portfolio: Portfolio,
    constraints: list[Constraint],
) -> JudgeVerdict:
    weights = {p.symbol: p.weight for p in portfolio.positions}
    payload = {
        "profil": {"resume": profile.assessment.summary, "libelle": profile.assessment.risk_label,
                   "horizon_annees": profile.form.horizon_years, "objectif": profile.form.objective},
        "contraintes": [describe(c) for c in constraints],
        "portefeuille": {
            "mandat": portfolio.mandate,
            "positions": [{"symbole": p.symbol, "nom": p.name, "poids": p.weight, "secteur": p.sector} for p in portfolio.positions],
            "indicateurs": portfolio.metrics.model_dump() if portfolio.metrics else None,
        },
    }
    opinion = await run_agent(
        bus=bus, label=f"Juge {portfolio.mandate}", step="8", kind="fast", system_prompt=SYSTEM,
        user_prompt="Évalue ce portefeuille.\n\n" + json.dumps(payload, ensure_ascii=False, indent=2),
        schema=JudgeOpinion, tools=make_judge_tools(market, weights, constraints),
        start_text=f"Vérification du portefeuille « {portfolio.mandate} »", done_text="Évaluation terminée",
    )
    checks = evaluate(market, weights, constraints)  # source de vérité de la conformité
    hard_fail = sum(1 for c in checks if c.constraint.hard and not c.passed)
    soft_fail = sum(1 for c in checks if not c.constraint.hard and not c.passed)
    return JudgeVerdict(
        portfolio_id=portfolio.id,
        compliant=hard_fail == 0,
        hard_violations=hard_fail,
        soft_violations=soft_fail,
        checks=checks,
        fit_score=opinion.fit_score,
        comment=opinion.comment,
        suggested_fixes=opinion.suggested_fixes,
    )
