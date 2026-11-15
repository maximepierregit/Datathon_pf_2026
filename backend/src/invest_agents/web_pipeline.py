"""Pipeline exposé au frontend: même flux d'agents, événements au format `PipelineEvent` (types.ts).

Correspondance avec les trois agents affichés par le frontend:

    Éclaireur    agent Profil + exclusions de l'univers         événements `agent_status`, `universe`
    Compositeur  traduction des préférences + 3 PM en parallèle `agent_status`
    Vérificateur 3 Juges, nouvel essai, CRO                     `agent_status`, `rerun`, `warning`

Événements ajoutés au contrat (ignorés par le frontend actuel tant qu'il ne les lit pas):
    {"type": "portfolios", "portfolios": {prudent, equilibre, conviction}}   avant `done`
    {"type": "thinking", "agent": AgentId, "source": str, "text": str}         réflexion des modèles
    {"type": "error", "code": str, "message": str}                            le flux s'arrête sans `done`
    {"type": "heartbeat"}                                                       toutes les 10 s sans activité
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from pydantic import BaseModel, ValidationError

from .agents.base import AgentError
from .agents.cro import run_cro
from .agents.judge import run_judge
from .agents.portfolio_manager import run_portfolio_manager
from .agents.profile import assemble_profile, run_profile_agent
from .config import get_settings
from .constraints import evaluate, excluded_mask
from .contract import (
    FrontendConstraints, FrontendProfile, coherence_warnings, global_exclusions, make_feasible,
    mandate_constraints, risk_score, to_frontend_portfolio, to_investor_form,
)
from .data import Market, get_market
from .events import EventBus
from .mandates import MANDATES, Mandate, vol_cap_for
from .schemas import (
    Constraint, InvestorForm, InvestorProfile, JudgeVerdict, Portfolio, ProfileAssessment, RiskReport,
)

logger = logging.getLogger(__name__)


class PipelineRequest(BaseModel):
    profile: FrontendProfile
    constraints: FrontendConstraints = FrontendConstraints()


@dataclass
class Plan:
    mandate: Mandate
    constraints: list[Constraint]
    notes: list[str]
    vol_cap: Optional[float]


# --------------------------------------------------------------------------- #
# Traduction des événements internes
# --------------------------------------------------------------------------- #
STEP_AGENT = {"3": "eclaireur", "3b": "eclaireur", "3c": "eclaireur", "4": "eclaireur",
              "5": "compositeur", "8": "verificateur", "9": "verificateur"}
TOOL_TEXT = {
    "describe_universe": "je fais le tour des placements disponibles…",
    "screen_assets": "je passe l’univers au crible…",
    "optimize_portfolio": "j’optimise la répartition…",
    "check_portfolio_constraints": "je vérifie chaque limite…",
}


def _who(label: Optional[str]) -> Optional[str]:
    for prefix in ("PM ", "Juge "):
        if label and label.startswith(prefix):
            return label[len(prefix):]
    return None


def to_frontend_event(ev: dict) -> Optional[dict]:
    t = ev["type"]
    if t == "fe":
        return ev["event"]
    if t == "heartbeat":
        return {"type": "heartbeat"}
    if t == "error":
        return {"type": "error", "code": ev.get("code", "internal"), "message": ev.get("message", "")}
    agent = STEP_AGENT.get(ev.get("step") or "")
    if agent is None:
        return None
    who = _who(ev.get("agent"))
    if t == "thinking":
        return {"type": "thinking", "agent": agent, "source": ev.get("agent"), "text": ev.get("text", "")}
    if t == "tool" and ev.get("name") in TOOL_TEXT:
        text = TOOL_TEXT[ev["name"]]
        return {"type": "agent_status", "agent": agent, "status": "running",
                "message": f"{who} : {text}" if who else text[0].upper() + text[1:]}
    if t == "status" and ev.get("text"):
        # Les fins d'agents individuels restent « en cours »: la fin d'étape est émise par le pipeline.
        text = ev["text"] if ev.get("state") == "start" or not who else f"{who} : {ev['text'][0].lower()}{ev['text'][1:]}."
        return {"type": "agent_status", "agent": agent, "status": "running", "message": text}
    return None


async def stream_web_pipeline(payload: dict) -> AsyncIterator[dict]:
    bus = EventBus()

    async def worker() -> None:
        try:
            await run_web_pipeline(payload, bus)
        except ValidationError as exc:
            details = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
            bus.emit("error", code="invalid_request", message=f"Requête invalide: {details}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Erreur dans le pipeline web")
            bus.emit("error", code="internal", message=f"Erreur interne ({type(exc).__name__}).")
        finally:
            bus.close()

    task = asyncio.create_task(worker())
    async for out in dedupe(bus.stream(task)):
        yield out


async def dedupe(events: AsyncIterator[dict]) -> AsyncIterator[dict]:
    """Traduit et retire les `agent_status` identiques au précédent du même agent."""
    last: dict[str, str] = {}
    async for ev in events:
        out = to_frontend_event(ev)
        if out is None:
            continue
        if out["type"] == "agent_status":
            key = f"{out['status']}|{out['message']}"
            if last.get(out["agent"]) == key:
                continue
            last[out["agent"]] = key
        yield out


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
_ASSESSMENTS: dict[str, ProfileAssessment] = {}


async def assess(bus: EventBus, form: InvestorForm, exclusions: list[Constraint]) -> ProfileAssessment:
    """Agent Profil, mis en cache dans le processus: un ajustement ne change pas le profil."""
    key = form.model_dump_json() + "|" + "|".join(sorted(f"{c.type.value}:{c.target}" for c in exclusions))
    if key not in _ASSESSMENTS:
        if len(_ASSESSMENTS) > 256:
            _ASSESSMENTS.clear()
        _ASSESSMENTS[key] = await run_profile_agent(bus, form, exclusions)
    return _ASSESSMENTS[key]


def _fe(bus: EventBus, **event) -> None:
    bus.emit("fe", event=event)


def _status(bus: EventBus, agent: str, status: str, message: str) -> None:
    _fe(bus, type="agent_status", agent=agent, status=status, message=message)


async def _build(bus: EventBus, market: Market, profile: InvestorProfile, plan: Plan, feedback: Optional[str]) -> Portfolio:
    md = plan.mandate
    try:
        return await run_portfolio_manager(bus, market, md, profile, plan.constraints, feedback, vol_cap=plan.vol_cap)
    except Exception as exc:  # noqa: BLE001
        logger.exception("PM %s en échec", md.id)
        return Portfolio(id=md.id, mandate=md.name, mandate_description=md.description, status="failed",
                         failure_reason=type(exc).__name__)


async def _judge(bus: EventBus, market: Market, profile: InvestorProfile, p: Portfolio, plan: Plan) -> JudgeVerdict:
    try:
        return await run_judge(bus, market, profile, p, plan.constraints)
    except Exception:  # noqa: BLE001
        logger.exception("Juge %s en échec", p.id)
        checks = evaluate(market, {x.symbol: x.weight for x in p.positions}, plan.constraints)
        hard = sum(1 for c in checks if c.constraint.hard and not c.passed)
        soft = sum(1 for c in checks if not c.constraint.hard and not c.passed)
        return JudgeVerdict(portfolio_id=p.id, compliant=hard == 0, hard_violations=hard, soft_violations=soft,
                            checks=checks, fit_score=0, comment="")


def _feedback(p: Portfolio, v: Optional[JudgeVerdict]) -> str:
    if p.status == "failed" or v is None:
        return f"Aucun portefeuille n'a pu être construit: {p.failure_reason}"
    lines = [f"- {c.label}: {c.message}" for c in v.checks if c.constraint.hard and not c.passed]
    return "\n".join(lines + [f"- Correction suggérée: {f}" for f in v.suggested_fixes])


async def run_web_pipeline(payload: dict, bus: EventBus) -> None:
    req = PipelineRequest.model_validate(payload)
    settings = get_settings()
    market = await asyncio.to_thread(get_market)
    score = risk_score(req.profile)
    fc = req.constraints

    # --- Éclaireur -------------------------------------------------------------------------------
    _fe(bus, type="pepite", text="C’est parti! Mes trois agents se mettent au travail.")
    _status(bus, "eclaireur", "running", "Lecture de ton profil et de tes préférences…")
    form = to_investor_form(req.profile)
    exclusions = global_exclusions(fc)
    assessment = await assess(bus, form, exclusions)
    profile = assemble_profile(form, exclusions, assessment)
    before = len(market.assets)
    after = int((~excluded_mask(market, exclusions)).sum())
    _fe(bus, type="universe", before=before, after=after)
    _status(bus, "eclaireur", "done", f"{after} placements retenus sur {before}.")

    # --- Compositeur -----------------------------------------------------------------------------
    _status(bus, "compositeur", "running", "Traduction de tes réponses en 3 ensembles de contraintes…")

    stock_cap = max(0.05, min(0.15, assessment.suggested_max_position_weight))

    def plan_for(md: Mandate) -> Plan:
        cons, notes = mandate_constraints(md, score, fc, market, stock_cap)
        cons, more, cap = make_feasible(market, md, cons, vol_cap_for(md, assessment.suggested_max_volatility))
        return Plan(md, cons, notes + more, cap)

    plans = {md.id: await asyncio.to_thread(plan_for, md) for md in MANDATES}
    _status(bus, "compositeur", "running", "Optimisation des portefeuilles Prudent, Équilibré et Conviction…")
    built = await asyncio.gather(*(_build(bus, market, profile, plans[md.id], None) for md in MANDATES))
    portfolios = {p.id: p for p in built}
    ok = sum(1 for p in built if p.status == "ok")
    _status(bus, "compositeur", "done", f"{ok} portefeuilles calculés.")

    # --- Vérificateur ----------------------------------------------------------------------------
    _status(bus, "verificateur", "running", "Relecture de chaque portefeuille…")

    async def judge_all(ids: list[str]) -> dict[str, JudgeVerdict]:
        ready = [i for i in ids if portfolios[i].status == "ok"]
        results = await asyncio.gather(*(_judge(bus, market, profile, portfolios[i], plans[i]) for i in ready))
        return dict(zip(ready, results))

    verdicts = await judge_all(list(portfolios))
    for _ in range(settings.max_pm_retries):
        failing = [i for i, p in portfolios.items() if p.status == "failed" or not verdicts.get(i, None) or not verdicts[i].compliant]
        if not failing:
            break
        for i in failing:
            _fe(bus, type="rerun", portfolio=i,
                reason="ne respecte pas encore toutes tes limites. Je le renvoie au Compositeur.")
        rebuilt = await asyncio.gather(
            *(_build(bus, market, profile, plans[i], _feedback(portfolios[i], verdicts.get(i))) for i in failing)
        )
        portfolios.update({p.id: p for p in rebuilt})
        verdicts.update(await judge_all(failing))
        fixed = [i for i in failing if verdicts.get(i) and verdicts[i].compliant]
        if fixed:
            names = ", ".join(plans[i].mandate.name for i in fixed)
            _status(bus, "verificateur", "running", f"Portefeuille {names} recalculé : c’est corrigé.")

    report: Optional[RiskReport] = None
    good = [p for p in portfolios.values() if p.status == "ok"]
    if good:
        try:
            report = await run_cro(bus, profile, good, verdicts)
        except AgentError:
            logger.exception("CRO en échec")

    for text in coherence_warnings(score, fc):
        _fe(bus, type="warning", text=text)
    if report:
        for issue in report.profile_inconsistencies:
            if issue.severity != "low":
                _fe(bus, type="warning", text=issue.detail)

    out: dict[str, dict] = {}
    for md in MANDATES:
        p, plan, v = portfolios[md.id], plans[md.id], verdicts.get(md.id)
        if p.status != "ok":
            continue
        warns = [] if md.id == "prudent" else coherence_warnings(score, fc)
        if report:
            warns += [f"{w.title} : {w.detail}" for w in report.warnings if w.portfolio_id == md.id and w.severity != "low"]
        if v and not v.compliant:
            warns += [f"Limite non respectée : {c.label} ({c.message})." for c in v.checks if c.constraint.hard and not c.passed]
        out[md.id] = to_frontend_portfolio(market, md, p, score, warns, plan.notes)

    all_ok = len(out) == len(MANDATES) and all(verdicts.get(i) and verdicts[i].compliant for i in out)
    _status(bus, "verificateur", "done",
            "Tout est cohérent avec les limites de sécurité." if all_ok
            else "Relecture terminée. Lis les avertissements avant de choisir.")
    _fe(bus, type="portfolios", portfolios=out)
    _fe(bus, type="pepite", text="Voilà! Trois propositions t’attendent. C’est toi qui choisis.")
    _fe(bus, type="done")
