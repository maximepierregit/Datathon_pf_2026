"""Les agents que Pépite appelle (gestionnaires, agents Risque, juge) et les opérations déterministes autour d'eux.

Chaque fonction ici est ce qu'un outil de Pépite exécute. Le code garde le dernier mot sur ce qui se chiffre:
poids et indicateurs (optimiseur), conformité (`constraints.evaluate`), limites du profil (`monport.build_profiles`).
Les agents proposent, jugent et expliquent.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from strands import tool

from ..agents.base import AgentError, AgentHandle
from ..diagnostics import diagnostics
from ..agents.portfolio_manager import make_pm_worker, run_pm_worker
from ..catalog import describe, evaluate, excluded_mask
from ..mandates import Mandate
from ..monport import (
    BASE_NAMES,
    SLOTS,
    VARIANT_NAMES,
    build_profiles,
    ensure_feasible,
    front,
    guidance_for,
    objective_for,
    pick_winner,
    status,
)
from ..tools import MACRO_PROMPT, make_macro_tools
from ..schemas import (
    ConstraintPlan,
    InvestorProfile,
    JudgeDecision,
    JudgeVerdict,
    Portfolio,
    RiskReport,
)
from .session import Session

logger = logging.getLogger(__name__)

# Les messages d'une question posée après coup (step « chat ») ne changent pas les cartes du pipeline.
CHAT_STEP = "chat"


def names_for(session: Session) -> dict[str, str]:
    return VARIANT_NAMES if session.coherent else BASE_NAMES


# --------------------------------------------------------------------------- #
# Plan de contraintes: Pépite propose, le code valide
# --------------------------------------------------------------------------- #
async def apply_plan(session: Session, plan: Optional[ConstraintPlan]) -> int:
    """Valide les 3 profils de Pépite (catalogue, exclusions, limites du profil). Retourne le nombre de profils que le
    code a dû remplacer. Sans plan, le code écrit lui-même les profils."""
    market = session.market
    profiles, replaced = build_profiles(plan, session.check, list(session.form.constraints), market.allowed_values())
    notes: dict[str, list[str]] = {s: [] for s in SLOTS}
    for slot in SLOTS:
        constraints, note = await asyncio.to_thread(ensure_feasible, market, profiles[slot][1])
        profiles[slot] = (profiles[slot][0], constraints)
        if note:
            notes[slot].append(note)
    session.profiles, session.notes = profiles, notes
    hard = [c for c in profiles["equilibre"][1] if c.hard]
    session.universe = (len(market.assets), int((~excluded_mask(market, hard)).sum()))
    if session.bus:
        front(session.bus, {"type": "universe", "before": session.universe[0], "after": session.universe[1]})
    return replaced


# --------------------------------------------------------------------------- #
# Agent Risque (un par gestionnaire)
# --------------------------------------------------------------------------- #
RISK_SYSTEM = """Tu es l'agent Risque du gestionnaire « {name} ». Tu relis son portefeuille avant qu'il passe au juge, et tu
cherches ce qui pourrait nuire à l'investisseur s'il n'en est pas averti.

1. `profile_inconsistencies`: incohérences du profil que ce portefeuille révèle (ex.: tolérance déclarée très élevée mais
   perte acceptée très faible; horizon court avec objectif de croissance agressive).
2. `warnings`: mises en garde sur ce portefeuille, avec `portfolio_id` = « {slot} ». Appuie-toi sur les indicateurs, sur
   la conformité et sur les `diagnostics` calculés par le système (concentration, perte maximale historique comparée à
   la perte acceptée, volatilité, préférences non respectées). Appelle `get_latest_macro_snapshot`: signale une
   exposition que le régime macro rend plus risquée (sensibilité aux taux, inflation, ralentissement de l'emploi).
3. `summary`: synthèse courte et directe.

LE CLIENT LIT TES MISES EN GARDE
Les `warnings` s'affichent telles quelles au client, souvent débutant, à côté de son portefeuille.
- `title`: 3 à 7 mots, une idée simple (« Beaucoup d'actions technologiques », « Baisse possible plus forte que prévu »).
- `detail`: une ou deux phrases courtes, 30 mots au plus, tutoyées, en français québécois. Dis ce qui peut arriver et
  pourquoi, avec au plus un chiffre parlant (« une baisse de 25 % en un an est déjà arrivée »). Pas de jargon:
  ni volatilité, ni VaR, ni drawdown, ni Sharpe, ni régime macro, ni symbole boursier sans son nom.
- Trois mises en garde au plus, les plus importantes d'abord.

RÈGLES
- Chaque point s'appuie sur un fait chiffré tiré du contexte ou des outils. N'invente aucun chiffre.
- Les rendements et risques sont historiques. Ils ne garantissent pas les résultats futurs. Rappelle-le une fois dans le résumé.
- Sois sobre: pas d'alarmisme, pas de recommandation d'achat. Gravité `high` seulement si le problème peut conduire
  l'investisseur à une perte supérieure à ce qu'il accepte ou à un portefeuille inadapté à son horizon. Un risque
  macro seul ne justifie pas `high`.
- Un problème que le gestionnaire peut corriger sans enfreindre les contraintes (concentration, diversification)
  s'écrit comme tel: le juge peut demander une réoptimisation. Ce qui vient des contraintes du client s'écrit aussi,
  mais n'est pas corrigeable.
- S'il n'y a rien à signaler, retourne des listes vides.

PLUS TARD
Pépite peut t'interroger sur ton rapport. Réponds alors en texte, avec les faits de ton rapport, sans rien recalculer.

""" + MACRO_PROMPT


def _portfolio_payload(session: Session, slot: str, p: Portfolio) -> dict:
    investor = session.investors[slot]
    weights = {x.symbol: x.weight for x in p.positions}
    checks = evaluate(session.market, weights, investor.constraints)
    return {
        "slot": slot,
        "mandat": p.mandate,
        "positions": [{"symbole": x.symbol, "nom": x.name, "poids": x.weight, "secteur": x.sector,
                       "classe": x.asset_class} for x in p.positions],
        "indicateurs": p.metrics.model_dump() if p.metrics else None,
        "resume_du_gestionnaire": p.summary,
        "compromis": p.tradeoffs,
        "ecarts": [f"{c.label}: {c.message}" for c in checks if not c.passed],
        "diagnostics": diagnostics(investor, p),
    }


async def run_risk(session: Session, slot: str) -> RiskReport:
    p = session.portfolios[slot]
    handle = session.risk_agents.get(slot)
    rebuilt = handle is not None
    if handle is None:
        handle = session.risk_agents[slot] = AgentHandle(
            label=f"Risque {p.mandate}", step="7", kind="strong", persistent=True,
            system_prompt=RISK_SYSTEM.format(name=p.mandate, slot=slot), tools=make_macro_tools(),
        )
    payload = {
        "profil": {
            "formulaire": session.form.model_dump(mode="json", exclude={"constraints"}),
            "evaluation": session.check.model_dump(mode="json", include={"risk_score", "risk_label", "summary", "coherent"}),
        },
        "portefeuille": _portfolio_payload(session, slot, p),
    }
    head = "Le gestionnaire a reconstruit son portefeuille. Refais ton rapport." if rebuilt else "Produis ton rapport de risque."
    report = await handle.run(
        session.bus, f"{head}\n\n" + json.dumps(payload, ensure_ascii=False, indent=2), RiskReport,
        start_text=f"Revue des risques du portefeuille « {p.mandate} »", done_text="Rapport de risque prêt",
    )
    for issue in report.warnings:  # le juge et le frontend retrouvent le portefeuille par son slot
        issue.portfolio_id = slot
    return report


# --------------------------------------------------------------------------- #
# Construction: gestionnaire, puis son agent Risque
# --------------------------------------------------------------------------- #
async def build_slots(session: Session, slots: list[str], instructions: dict[str, str]) -> None:
    bus, market, check = session.bus, session.market, session.check
    names = names_for(session)

    async def one(slot: str) -> None:
        investor = InvestorProfile(form=session.form, assessment=check, constraints=session.profiles[slot][1])
        session.investors[slot] = investor
        objective, aversion = objective_for(slot, check)
        mandate = Mandate(id=slot, name=names[slot], objective=objective, description=session.profiles[slot][0],
                          guidance=guidance_for(aversion), vol_cap_factor=None, risk_aversion=aversion)
        worker = session.workers.get(slot)
        if worker is None:
            worker = session.workers[slot] = make_pm_worker(market, mandate, investor, investor.constraints)
        elif instructions.get(slot):
            front(bus, {"type": "rerun", "portfolio": slot, "reason": instructions[slot][:300]})
        try:
            p = await run_pm_worker(bus, market, worker, mandate, investor, investor.constraints, instructions.get(slot))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Gestionnaire %s en échec", slot)
            p = Portfolio(id=slot, mandate=mandate.name, mandate_description=mandate.description,
                          status="failed", failure_reason=type(exc).__name__)
        session.portfolios[slot] = p
        session.reports.pop(slot, None)
        if p.status == "ok":  # le binôme: l'agent Risque relit aussitôt le portefeuille de son gestionnaire
            try:
                session.reports[slot] = await run_risk(session, slot)
            except AgentError:
                logger.exception("Agent Risque %s en échec", slot)

    await asyncio.gather(*(one(s) for s in slots))
    session.build_round += 1
    session.version += 1


# --------------------------------------------------------------------------- #
# Juge
# --------------------------------------------------------------------------- #
JUDGE_SYSTEM = """Tu es le juge de MonPort. Trois gestionnaires ont chacun construit un portefeuille pour le même client, et
leur agent Risque l'a relu. Tu reçois les portefeuilles, la conformité calculée par le code et les rapports de risque.

1. Appelle `check_portfolio_constraints` pour chaque portefeuille. Ses résultats font foi: ne les contredis jamais.
2. `opinions`: un avis par portefeuille construit (adéquation de 0 à 10, commentaire, corrections suggérées).
3. Rapport de risque: lis-le avec soin. Demande une réoptimisation (`reoptimize`, avec des instructions précises)
   seulement si c'est sérieux et corrigeable: une mise en garde de gravité `high` que le gestionnaire peut régler sans
   enfreindre ses contraintes dures, ou un rapport incomplet qui contredit les indicateurs. Une mise en garde `low`
   ou `medium`, un risque normal pour le profil ou un problème qui vient des contraintes du client ne justifie pas de
   reconstruire: mentionne-le dans l'avis. Une reconstruction coûte cher: en cas de doute, ne la demande pas.
4. Un portefeuille non conforme (contrainte dure) est reconstruit d'office par le code: inutile de le demander.
5. PROFIL COHÉRENT: les trois portefeuilles sont des variantes en concurrence. Désigne le meilleur dans `winner`:
   celui qui correspond le mieux au profil (niveau de risque, horizon, objectif), qui respecte le mieux les thèmes
   et les préférences du client, puis la diversification, le rendement espéré pour le risque pris et la tenue probable
   dans le régime macro actuel (`get_latest_macro_snapshot`). Un portefeuille
   non conforme ne gagne que si aucun ne l'est. `justification`: deux ou trois phrases tutoyées qui expliquent
   pourquoi ce portefeuille correspond le mieux au profil, sans le recommander (jamais « je te recommande », « tu
   devrais »: c'est le client qui décide), sans jargon (ni Sharpe, ni volatilité, ni écart-type, ni drawdown): « le meilleur rendement pour
   le risque pris », « des variations plus douces ». Seulement des chiffres fournis, à une décimale au plus.
6. PROFIL INCOHÉRENT: les trois portefeuilles sont trois bases (« Ton profil », « Tes contraintes », « Tes
   préférences »). Le client choisira. `winner` vaut null et `justification` est vide.

PLUS TARD
Pépite peut t'interroger sur ta décision. Réponds alors en texte, avec les faits de ton analyse.

""" + MACRO_PROMPT


def _verdict(session: Session, slot: str, decision: JudgeDecision) -> JudgeVerdict:
    p = session.portfolios[slot]
    checks = evaluate(session.market, {x.symbol: x.weight for x in p.positions}, session.investors[slot].constraints)
    hard = sum(1 for c in checks if c.constraint.hard and not c.passed)
    soft = sum(1 for c in checks if not c.constraint.hard and not c.passed)
    opinion = next((o for o in decision.opinions if o.slot == slot), None)
    return JudgeVerdict(
        portfolio_id=slot, compliant=hard == 0, hard_violations=hard, soft_violations=soft, checks=checks,
        fit_score=opinion.fit_score if opinion else 0,
        comment=opinion.comment if opinion else "Avis indisponible.",
        suggested_fixes=opinion.suggested_fixes if opinion else [],
    )


def _judge_tools(session: Session) -> list:
    @tool
    def check_portfolio_constraints(slot: str) -> dict:
        """Vérifie un portefeuille contre chaque contrainte de son profil (dures et préférences), calculé par le code.

        Args:
            slot: Le portefeuille à vérifier: "prudent", "equilibre" ou "conviction".
        """
        p = session.portfolios.get(slot)
        if p is None or p.status != "ok":
            return {"error": f"Aucun portefeuille construit pour « {slot} »."}
        checks = evaluate(session.market, {x.symbol: x.weight for x in p.positions}, session.investors[slot].constraints)
        return {
            "all_hard_respected": all(c.passed for c in checks if c.constraint.hard),
            "checks": [{"label": c.label, "hard": c.constraint.hard, "passed": c.passed, "actual": c.actual,
                        "limit": c.limit} for c in checks],
        }

    return [check_portfolio_constraints, *make_macro_tools()]


def _correction_text(v: JudgeVerdict) -> str:
    lines = [f"- {c.label}: {c.message}" for c in v.checks if c.constraint.hard and not c.passed]
    return "\n".join(lines + [f"- Correction suggérée: {f}" for f in v.suggested_fixes])


async def judge_round(session: Session) -> None:
    """Le juge compare les portefeuilles, la conformité est calculée par le code. Remplit verdicts, gagnant et relances."""
    bus = session.bus
    built = session.built()
    if session.judge is None:
        session.judge = AgentHandle(label="Juge final", step="8", kind="strong", system_prompt=JUDGE_SYSTEM,
                                    tools=_judge_tools(session), persistent=True)
    payload = {
        "profil": {"resume": session.check.summary, "libelle": session.check.risk_label, "coherent": session.coherent,
                   "horizon_annees": session.form.horizon_years, "objectif": session.form.objective,
                   "preferences": [describe(c) for c in session.form.constraints]},
        "portefeuilles": [
            {**_portfolio_payload(session, p.id, p),
             "rapport_de_risque": session.reports[p.id].model_dump(mode="json") if p.id in session.reports else None}
            for p in built
        ],
    }
    try:
        decision = await session.judge.run(
            bus, "Juge ces portefeuilles.\n\n" + json.dumps(payload, ensure_ascii=False, indent=2), JudgeDecision,
            start_text=f"Comparaison des {len(built)} portefeuilles" if session.coherent else "Vérification des portefeuilles",
            done_text="Décision rendue",
        )
    except AgentError:
        logger.exception("Juge en échec, verdicts calculés par le code")
        decision = JudgeDecision(opinions=[])

    session.decision = decision
    session.verdicts = {p.id: _verdict(session, p.id, decision) for p in built}
    session.judged_round = session.build_round

    # Demandes de réoptimisation: celles du juge, et le code ajoute tout portefeuille non conforme ou en échec.
    requests = {r.slot: r.instructions for r in decision.reoptimize if r.slot in session.portfolios}
    for slot in SLOTS:
        p = session.portfolios.get(slot)
        if p is None:
            continue
        if p.status == "failed":
            requests[slot] = f"Aucun portefeuille n'a pu être construit: {p.failure_reason}"
        elif not session.verdicts[slot].compliant:
            requests[slot] = "\n".join(filter(None, [requests.get(slot), _correction_text(session.verdicts[slot])]))
    session.reoptimize = requests

    if session.coherent:  # un seul gagnant: le choix du juge, sauf si le code le contredit sur la conformité
        winner = pick_winner(built, session.verdicts, decision.winner) if built else None
        session.winner = winner.id if winner else None
        session.justification = decision.justification if winner and winner.id == decision.winner else (
            f"La {winner.mandate.lower()} respecte le mieux tes limites, avec la meilleure note du juge." if winner else "")
    else:
        session.winner, session.justification = None, ""

    for slot, v in session.verdicts.items():
        text = ("Toutes tes limites sont respectées." if v.compliant else f"{v.hard_violations} limite(s) non respectée(s).")
        front(bus, status(f"juge-{slot}", "done", text))
    if session.winner:
        front(bus, status("juge-final", "done", f"La {session.portfolios[session.winner].mandate.lower()} l’emporte."))
    else:
        front(bus, status("juge-final", "done", "Conformité vérifiée pour chaque portefeuille."))


# --------------------------------------------------------------------------- #
# Justifications (ce que les agents ont déjà produit) et questions posées après coup
# --------------------------------------------------------------------------- #
def justifications(session: Session, slot: str) -> dict:
    p = session.portfolios.get(slot)
    if p is None:
        return {"error": f"Aucun portefeuille pour « {slot} »."}
    worker, report, v = session.workers.get(slot), session.reports.get(slot), session.verdicts.get(slot)
    notes = [{"symbole": x.symbol, "poids": x.weight, "role": x.rationale} for x in p.positions[:10]]
    return {
        "portefeuille": p.mandate,
        "consigne_recue": session.profiles.get(slot, ("", []))[0],
        "contraintes": [describe(c) for c in session.profiles.get(slot, ("", []))[1]],
        "gestionnaire": {"resume": p.summary, "compromis": p.tradeoffs, "principales_positions": notes},
        "indicateurs": p.metrics.model_dump(exclude={"hhi"}) if p.metrics else None,
        "risque": report.model_dump(mode="json") if report else None,
        "juge": {"conforme": v.compliant, "note": v.fit_score, "avis": v.comment, "corrections": v.suggested_fixes} if v else None,
        "gagnant": session.winner == slot,
        "essais_du_gestionnaire": worker.state.log if worker else [],
    }


def _question(question: str) -> str:
    return (f"Pépite te transmet une question du client:\n« {question} »\n\nRéponds à Pépite en texte, en 3 à 6 phrases: "
            "les faits de ton travail, sans rien recalculer ni inventer de chiffre. Si tu ne sais pas, dis-le.")


async def ask_agent(session: Session, who: str, slot: Optional[str], question: str) -> str:
    """Pépite interroge un gestionnaire (`pm`), un agent Risque (`risk`) ou le juge (`judge`)."""
    bus = session.bus
    if who == "judge":
        handle, name = session.judge, "le juge"
    elif who == "risk":
        handle, name = session.risk_agents.get(slot or ""), f"l'agent Risque du portefeuille « {slot} »"
    else:
        worker = session.workers.get(slot or "")
        handle, name = (worker.handle if worker else None), f"le gestionnaire du portefeuille « {slot} »"
        if worker:
            worker.state.read_only = True
    if handle is None:
        return f"Impossible: {name} n'a rien construit pour l'instant."
    return await handle.ask(bus, _question(question), step=CHAT_STEP, start_text="Question de Pépite",
                            done_text="Réponse envoyée à Pépite")
