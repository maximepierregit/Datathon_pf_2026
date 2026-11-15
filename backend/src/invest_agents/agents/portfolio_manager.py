"""Gestionnaires de portefeuille (étape 5): sélectionnent les titres, l'optimiseur calcule les poids.

Le modèle choisit les titres et rédige l'explication. Les poids et toutes les métriques viennent de
`optimizer.optimize`, jamais du texte du modèle.
"""

from __future__ import annotations

import json
from typing import Literal, Optional

from ..constraints import describe
from ..data import Market
from ..events import EventBus
from ..mandates import Mandate, vol_cap_for
from ..optimizer import optimize
from ..schemas import Constraint, InvestorProfile, PMNarrative, Portfolio, Position
from ..tools import PMState, fallback_selection, make_pm_tools
from .base import AgentError, run_agent

SYSTEM_TEMPLATE = """Tu es le gestionnaire de portefeuille « {name} » d'un service de conseil en placement canadien (CAD).
Mandat: {description}
Style: {guidance}

DÉMARCHE
1. Appelle `describe_universe`, puis `screen_assets` (plusieurs fois, avec des filtres différents) pour repérer des candidats.
   Pour chaque contrainte de poids minimal (classe d'actifs, région, thématique, facteur), sélectionne plusieurs
   placements du groupe concerné, sinon l'optimisation sera impossible.
2. Choisis entre {low} et {high} placements. Diversifie par classe d'actifs, région et secteur.
3. Appelle `optimize_portfolio` avec ta sélection. Les contraintes dures de l'utilisateur sont appliquées par l'outil;
   tu ne peux ni les changer ni les contourner.
4. Si le statut est `infeasible` ou `invalid_selection`, lis le message, corrige la sélection et recommence.
   Au plus {attempts} appels à `optimize_portfolio` au total.
5. Le dernier appel réussi (statut `optimal` ou `feasible`) est ton portefeuille. Rédige ensuite ta réponse finale.

Dans ta réponse finale: un résumé de stratégie, une note par position principale (au moins les 8 plus lourdes)
et les compromis, en t'adressant au client (tutoiement, 1 à 2 phrases courtes chacun). N'écris aucun poids ni indicateur qui ne vient pas de l'outil, et ne parle jamais des outils au client."""

MAX_ATTEMPTS = 6


def _prompt(profile: InvestorProfile, constraints: list[Constraint], feedback: Optional[str]) -> str:
    payload = {
        "profil": {
            "resume": profile.assessment.summary,
            "score_risque": profile.assessment.risk_score,
            "libelle": profile.assessment.risk_label,
            "horizon_annees": profile.form.horizon_years,
            "montant_cad": profile.form.investment_amount_cad,
            "objectif": profile.form.objective,
        },
        "contraintes": [describe(c) for c in constraints],
    }
    text = "Construis ton portefeuille pour cet investisseur.\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    if feedback:
        text += (
            "\n\nUne tentative précédente n'a pas été retenue. Corrige-la en tenant compte de ces écarts:\n" + feedback
        )
    return text


def _positions(market: Market, weights: dict[str, float], narrative: Optional[PMNarrative]) -> list[Position]:
    notes = {n.symbol.lower(): n.rationale for n in (narrative.position_notes if narrative else [])}
    out = []
    for symbol, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        if w <= 0:
            continue
        a = market.assets.loc[symbol]
        out.append(
            Position(
                symbol=symbol, name=str(a["name"]), weight=round(w, 4), sector=str(a["sector"]),
                country=str(a["country"]), asset_class=str(a["asset_class"]), rationale=notes.get(symbol.lower()),
            )
        )
    return out


async def run_portfolio_manager(
    bus: EventBus,
    market: Market,
    mandate: Mandate,
    profile: InvestorProfile,
    pm_constraints: list[Constraint],
    feedback: Optional[str] = None,
    vol_cap: Optional[float] | Literal["mandate"] = "mandate",
) -> Portfolio:
    """`vol_cap="mandate"` applique le plafond du mandat; une valeur (ou None) le remplace."""
    label = f"PM {mandate.name}"
    state = PMState(
        constraints=pm_constraints,
        objective=mandate.objective,
        vol_cap=vol_cap_for(mandate, profile.assessment.suggested_max_volatility) if vol_cap == "mandate" else vol_cap,
    )
    min_n = max([int(c.value) for c in pm_constraints if c.hard and c.type.value == "min_positions" and c.value] + [8])
    max_n = min([20] + [int(c.value) for c in pm_constraints if c.hard and c.type.value == "max_positions" and c.value])
    system = SYSTEM_TEMPLATE.format(
        name=mandate.name, description=mandate.description, guidance=mandate.guidance,
        low=min(min_n, max_n), high=max_n, attempts=MAX_ATTEMPTS,
    )
    narrative: Optional[PMNarrative] = None
    try:
        narrative = await run_agent(
            bus=bus, label=label, step="5", kind="strong", system_prompt=system,
            user_prompt=_prompt(profile, pm_constraints, feedback), schema=PMNarrative,
            tools=make_pm_tools(market, state), start_text=f"Construction du portefeuille « {mandate.name} »",
            done_text="Portefeuille construit",
        )
    except AgentError as exc:
        bus.emit("status", step="5", agent=label, state="warning", text="Le gestionnaire a échoué, sélection de repli")
        state.log.append(str(exc))

    if state.best is None:  # filet de sécurité: le pipeline continue même si le PM n'a pas abouti
        selection = fallback_selection(market, pm_constraints, mandate.objective)
        result = optimize(market, selection, mandate.objective, pm_constraints, vol_cap=state.vol_cap)
        if result.ok:
            state.best = result
            bus.emit("status", step="5", agent=label, state="warning", text="Portefeuille obtenu par sélection de repli")
        else:
            return Portfolio(
                id=mandate.id, mandate=mandate.name, mandate_description=mandate.description, status="failed",
                failure_reason=result.message,
            )

    best = state.best
    return Portfolio(
        id=mandate.id,
        mandate=mandate.name,
        mandate_description=mandate.description,
        positions=_positions(market, best.weights, narrative),
        metrics=best.metrics,
        summary=narrative.summary if narrative else "Portefeuille obtenu par sélection automatique de repli.",
        tradeoffs=narrative.tradeoffs if narrative else "",
    )
