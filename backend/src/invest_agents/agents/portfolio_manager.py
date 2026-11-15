"""Gestionnaires de portefeuille (étape 5): sélectionnent les titres, l'optimiseur calcule les poids.

Le modèle choisit les titres et rédige l'explication. Les poids et toutes les métriques viennent de
`optimizer.optimize`, jamais du texte du modèle.

Un `PMWorker` garde son agent: on peut le relancer avec des consignes (réoptimisation) et l'interroger ensuite sur
ses choix, avec la mémoire de ses essais.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from ..catalog import describe
from ..market import Market
from ..events import EventBus
from ..mandates import Mandate, vol_cap_for
from ..allocator import optimize
from ..schemas import Constraint, InvestorProfile, PMNarrative, Portfolio, Position
from ..tools import MACRO_PROMPT, PMState, fallback_selection, make_pm_tools
from .base import AgentError, AgentHandle

SYSTEM_TEMPLATE = """Tu es le gestionnaire de portefeuille « {name} » d'un service de conseil en placement canadien (CAD).
Mandat: {description}
Style: {guidance}

DÉMARCHE
1. Appelle `get_latest_macro_snapshot` pour situer le régime macro, puis `describe_universe` et `screen_assets`
   (plusieurs fois, avec des filtres différents) pour repérer des candidats.
2. Choisis entre {low} et {high} titres. Diversifie par secteur, pays et classe d'actifs. Le régime macro peut orienter
   tes choix (par exemple la part d'obligations selon le niveau des taux), dans le respect de ton mandat.
3. Appelle `optimize_portfolio` avec ta sélection. Les contraintes dures de l'utilisateur sont appliquées par l'outil;
   tu ne peux ni les changer ni les contourner.
4. Si le statut est `infeasible` ou `invalid_selection`, lis le message, corrige la sélection et recommence.
   Au plus {attempts} appels à `optimize_portfolio` au total.
5. Le dernier appel réussi (statut `optimal` ou `feasible`) est ton portefeuille. Rédige ensuite ta réponse finale.

Dans ta réponse finale: un résumé de stratégie (avec, en une phrase, le régime macro retenu), une note par position
principale (au moins les 8 plus lourdes) et les compromis. N'écris aucun poids ni indicateur qui ne vient pas de l'outil.

PLUS TARD
Pépite, l'agente qui parle au client, peut te redemander de reconstruire ton portefeuille (le juge ou le client
l'exige) ou te demander de justifier tes choix. Pour une justification, réponds en texte, avec les faits de tes
essais et de tes outils: pourquoi ces titres, pourquoi ces poids, quels compromis. Tu ne recalcules rien alors."""

MAX_ATTEMPTS = 6


@dataclass
class PMWorker:
    mandate: Mandate
    state: PMState
    handle: AgentHandle
    narrative: Optional[PMNarrative] = None
    builds: int = 0


def _prompt(mandate: Mandate, profile: InvestorProfile, constraints: list[Constraint], feedback: Optional[str],
            rebuild: bool) -> str:
    payload = {
        "mandat": {"nom": mandate.name, "description": mandate.description, "style": mandate.guidance},
        "profil": {
            "resume": profile.assessment.summary,
            "score_risque": profile.assessment.risk_score,
            "libelle": profile.assessment.risk_label,
            "aversion_au_risque": mandate.risk_aversion,
            "horizon_annees": profile.form.horizon_years,
            "montant_cad": profile.form.investment_amount_cad,
            "objectif": profile.form.objective,
        },
        "contraintes": [describe(c) for c in constraints],
    }
    head = "Reconstruis ton portefeuille." if rebuild else "Construis ton portefeuille pour cet investisseur."
    text = head + "\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    if feedback:
        text += "\n\nCorrige ton portefeuille en tenant compte de ces consignes:\n" + feedback
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


def make_pm_worker(market: Market, mandate: Mandate, profile: InvestorProfile,
                   pm_constraints: list[Constraint]) -> PMWorker:
    state = PMState(
        constraints=pm_constraints,
        objective=mandate.objective,
        vol_cap=vol_cap_for(mandate, profile.assessment.suggested_max_volatility),
        risk_aversion=mandate.risk_aversion,
    )
    min_n = max([int(c.value) for c in pm_constraints if c.hard and c.type.value == "min_positions" and c.value] + [8])
    max_n = min([20] + [int(c.value) for c in pm_constraints if c.hard and c.type.value == "max_positions" and c.value])
    system = SYSTEM_TEMPLATE.format(
        name=mandate.name, description=mandate.description, guidance=mandate.guidance,
        low=min(min_n, max_n), high=max_n, attempts=MAX_ATTEMPTS,
    ) + "\n\n" + MACRO_PROMPT
    handle = AgentHandle(label=f"PM {mandate.name}", step="5", kind="strong", system_prompt=system,
                         tools=make_pm_tools(market, state), persistent=True)
    return PMWorker(mandate=mandate, state=state, handle=handle)


async def run_pm_worker(
    bus: EventBus,
    market: Market,
    worker: PMWorker,
    mandate: Mandate,
    profile: InvestorProfile,
    pm_constraints: list[Constraint],
    feedback: Optional[str] = None,
) -> Portfolio:
    """Construit (ou reconstruit) le portefeuille. `mandate` et les contraintes peuvent avoir changé depuis le dernier tour."""
    label = worker.handle.label
    state = worker.state
    rebuild = worker.builds > 0
    worker.builds += 1
    worker.mandate = mandate
    state.constraints, state.objective, state.risk_aversion = pm_constraints, mandate.objective, mandate.risk_aversion
    state.vol_cap = vol_cap_for(mandate, profile.assessment.suggested_max_volatility)
    state.best, state.attempts, state.read_only = None, 0, False
    try:
        worker.narrative = await worker.handle.run(
            bus, _prompt(mandate, profile, pm_constraints, feedback, rebuild), PMNarrative,
            start_text=f"{'Reconstruction' if rebuild else 'Construction'} du portefeuille « {mandate.name} »",
            done_text="Portefeuille construit",
        )
    except AgentError as exc:
        worker.narrative = None
        bus.emit("status", step="5", agent=label, state="warning", text="Le gestionnaire a échoué, sélection de repli")
        state.log.append(str(exc))

    if state.best is None:  # filet de sécurité: le pipeline continue même si le PM n'a pas abouti
        selection = fallback_selection(market, pm_constraints, mandate.objective)
        result = optimize(market, selection, mandate.objective, pm_constraints, vol_cap=state.vol_cap,
                          risk_aversion=mandate.risk_aversion)
        if result.ok:
            state.best = result
            bus.emit("status", step="5", agent=label, state="warning", text="Portefeuille obtenu par sélection de repli")
        else:
            state.read_only = True
            return Portfolio(
                id=mandate.id, mandate=mandate.name, mandate_description=mandate.description, status="failed",
                failure_reason=result.message,
            )

    state.read_only = True  # les questions ultérieures portent sur ce portefeuille: il ne change plus
    best = state.best
    narrative = worker.narrative
    return Portfolio(
        id=mandate.id,
        mandate=mandate.name,
        mandate_description=mandate.description,
        positions=_positions(market, best.weights, narrative),
        metrics=best.metrics,
        summary=narrative.summary if narrative else "Portefeuille obtenu par sélection automatique de repli.",
        tradeoffs=narrative.tradeoffs if narrative else "",
    )


async def run_portfolio_manager(
    bus: EventBus,
    market: Market,
    mandate: Mandate,
    profile: InvestorProfile,
    pm_constraints: list[Constraint],
    feedback: Optional[str] = None,
) -> Portfolio:
    """Une construction sans suite (ancien pipeline `orchestrator.py`)."""
    worker = make_pm_worker(market, mandate, profile, pm_constraints)
    return await run_pm_worker(bus, market, worker, mandate, profile, pm_constraints, feedback)
