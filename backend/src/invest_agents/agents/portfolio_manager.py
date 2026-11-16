"""Gestionnaires de portefeuille (étape 5): l'optimiseur choisit les titres ET les poids, le gestionnaire explique.

Le portefeuille vient de `allocator.optimize_universe`: Markowitz sur tous les titres admissibles (questionnaire puis
filtre d'historique depuis 2021), puis 25 à 60 positions détenues (cible 50). Le modèle ne sélectionne aucun titre
et n'impose aucun poids: il lit le résultat (`get_portfolio`), le situe dans le régime macro et rédige l'explication.

Un `PMWorker` garde son agent: on peut l'interroger ensuite sur le portefeuille, avec la mémoire de son analyse.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Optional

from ..catalog import describe
from ..market import Market
from ..events import EventBus
from ..mandates import Mandate, vol_cap_for
from ..allocator import optimize_with_relaxation
from ..schemas import Constraint, InvestorProfile, PMNarrative, Portfolio, Position
from ..tools import MACRO_PROMPT, PMState, make_explain_tools
from .base import AgentError, AgentHandle

SYSTEM_TEMPLATE = """Tu es le gestionnaire de portefeuille « {name} » d'un service de conseil en placement canadien (CAD).
Mandat: {description}
Style: {guidance}

LE PORTEFEUILLE EST DÉJÀ CALCULÉ
L'optimiseur a considéré tous les titres admissibles (après les contraintes du client et le filtre d'historique),
avec leurs rendements espérés et leurs covariances, puis a retenu les positions détenues et leurs poids. Tu ne
choisis aucun titre et tu ne changes aucun poids: tu expliques le résultat.

DÉMARCHE
1. Appelle `get_portfolio` pour lire les poids, les indicateurs et la trace du calcul, et
   `get_latest_macro_snapshot` pour situer le régime macro.
2. Rédige ta réponse finale: un résumé de stratégie (avec, en une phrase, le régime macro retenu), une note par
   position principale (au moins les 8 plus lourdes: son rôle, par exemple diversification ou rendement) et les
   compromis (limites actives, concentration, ce que les contraintes du client ont coûté).
N'écris aucun poids ni indicateur qui ne vient pas de `get_portfolio`.

PLUS TARD
Pépite peut te demander de justifier le portefeuille ou de tenir compte de consignes du juge. Le calcul ne dépend
pas de toi: explique ce que les consignes changeraient et pourquoi l'optimiseur a fait ces choix. Tu ne recalcules rien."""


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
    head = ("Le portefeuille a été recalculé. Explique-le de nouveau." if rebuild
            else "Explique le portefeuille calculé pour cet investisseur.")
    text = head + "\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    if feedback:
        text += ("\n\nConsignes reçues (juge ou client). Le calcul ne dépend pas de toi: explique dans tes compromis "
                 "ce qu'elles impliquent et ce que les contraintes permettent:\n" + feedback)
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
    system = SYSTEM_TEMPLATE.format(name=mandate.name, description=mandate.description,
                                    guidance=mandate.guidance) + "\n\n" + MACRO_PROMPT
    handle = AgentHandle(label=f"PM {mandate.name}", step="5", kind="strong", system_prompt=system,
                         tools=make_explain_tools(state), persistent=True)
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
    """Calcule le portefeuille (Markowitz global, par le code), puis fait rédiger son explication par le modèle."""
    label = worker.handle.label
    state = worker.state
    rebuild = worker.builds > 0
    worker.builds += 1
    worker.mandate = mandate
    state.constraints, state.objective, state.risk_aversion = pm_constraints, mandate.objective, mandate.risk_aversion
    state.vol_cap = vol_cap_for(mandate, profile.assessment.suggested_max_volatility)
    state.best, state.attempts, state.read_only = None, 0, True  # aucun outil ne modifie le portefeuille

    card = f"gestionnaire-{mandate.id}"
    bus.emit("tool", step="5", agent=label, name="optimize_portfolio")
    # Échec sur les contraintes dures: le code relance aussitôt avec des contraintes assouplies (préférences).
    run = await asyncio.to_thread(optimize_with_relaxation, market, mandate.objective, pm_constraints,
                                  vol_cap=state.vol_cap, risk_aversion=mandate.risk_aversion)
    result = run.result
    relaxed = [describe(c.model_copy(update={"hard": True})) for c in run.relaxed]  # libellé sans « (préférence) »
    if run.first_failure:
        state.log.append(f"Markowitz global: infeasible ({run.first_failure})")
        state.log.append(f"Relance avec contraintes assouplies: {result.status} ({result.message})")
        if result.ok:
            bus.emit("front", event=_card(card, "running", "Contraintes trop serrées : nouveau calcul avec des limites assouplies…"))
            bus.emit("front", event={"type": "warning", "text": relaunch_text(mandate.name, relaxed)})
    else:
        state.log.append(f"Markowitz global: {result.status} ({result.message})")
    if not result.ok:
        bus.emit("front", event=_card(card, "done", "Aucun portefeuille possible, même avec des limites assouplies."))
        return Portfolio(id=mandate.id, mandate=mandate.name, mandate_description=mandate.description,
                         status="failed", failure_reason=result.message, diagnostics=result.diagnostics)
    state.best, state.constraints = result, run.constraints
    if run.first_failure:
        feedback = "\n\n".join(filter(None, [feedback, (
            "Le premier calcul a échoué (" + run.first_failure + "). Le code l'a relancé avec des contraintes "
            "assouplies, devenues des préférences: " + (", ".join(relaxed) or "plafond de risque du mandat") +
            ". Dis-le clairement dans tes compromis.")]))
    try:
        worker.narrative = await worker.handle.run(
            bus, _prompt(mandate, profile, run.constraints, feedback, rebuild), PMNarrative,
            start_text=f"{'Explication renouvelée' if rebuild else 'Explication'} du portefeuille « {mandate.name} »",
            done_text="Portefeuille construit",
        )
    except AgentError as exc:
        worker.narrative = None
        bus.emit("status", step="5", agent=label, state="warning", text="Explication indisponible, portefeuille conservé")
        state.log.append(str(exc))

    narrative = worker.narrative
    return Portfolio(
        id=mandate.id,
        mandate=mandate.name,
        mandate_description=mandate.description,
        positions=_positions(market, result.weights, narrative),
        metrics=result.metrics,
        summary=narrative.summary if narrative else result.message,
        tradeoffs=narrative.tradeoffs if narrative else "",
        relaunch_reason=run.first_failure,
        relaxed=relaxed,
        diagnostics=result.diagnostics,
    )


def _card(card: str, state: str, message: str) -> dict:
    return {"type": "agent_status", "agent": card, "status": state, "message": message}


def relaunch_text(name: str, relaxed: list[str]) -> str:
    """L'avertissement montré au client quand un portefeuille a été relancé avec des contraintes assouplies."""
    what = ("Ces limites sont devenues de simples préférences : " + "; ".join(relaxed) + "." if relaxed
            else "Le plafond de risque prévu pour ce portefeuille a été levé.")
    return (f"Le portefeuille « {name} » n’a pas pu respecter toutes tes limites. Je l’ai recalculé avec des "
            f"limites assouplies. {what}")
