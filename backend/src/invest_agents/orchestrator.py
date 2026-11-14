"""Orchestrateur déterministe du pipeline (étapes 3 à 10 du schéma).

Le flux est fixe, donc écrit en code Python plutôt que confié à un agent superviseur:

    initial:  formulaire ──────────────────────────────▶ Profil
    refine :  message libre ▶ Extraction ▶ Fusion ▶ Profil
    ensuite:  3 PM en parallèle ▶ 3 Juges en parallèle ▶ (nouvel essai limité si aucun conforme) ▶ CRO ▶ résultat

Les agents dialoguent avec le frontend uniquement par le bus d'événements.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Optional

from pydantic import ValidationError

from .agents.base import AgentError
from .agents.cro import run_cro
from .agents.extraction import run_extraction_agent
from .agents.judge import run_judge
from .agents.portfolio_manager import run_portfolio_manager
from .agents.profile import assemble_profile, run_profile_agent
from .config import get_settings
from .constraints import describe, detect_conflicts, evaluate, merge_constraints, validate_all
from .data import Market, get_market
from .events import EventBus
from .mandates import MANDATES, Mandate
from .schemas import Constraint, InvestorForm, InvestorProfile, JudgeVerdict, Portfolio, RiskReport

logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 2000


class PipelineError(Exception):
    def __init__(self, code: str, message: str, details: Optional[list[str]] = None) -> None:
        super().__init__(message)
        self.code, self.details = code, details or []


# --------------------------------------------------------------------------- #
# Point d'entrée
# --------------------------------------------------------------------------- #
async def stream_pipeline(payload: dict) -> AsyncIterator[dict]:
    """Exécute le pipeline et produit les événements au fur et à mesure."""
    bus = EventBus()

    async def worker() -> None:
        try:
            await run_pipeline(payload, bus)
        except PipelineError as exc:
            bus.emit("error", code=exc.code, message=str(exc), details=exc.details)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Erreur inattendue dans le pipeline")
            bus.emit("error", code="internal", message=f"Erreur interne ({type(exc).__name__}).", details=[])
        finally:
            bus.close()

    task = asyncio.create_task(worker())
    async for event in bus.stream(task):
        yield event


# --------------------------------------------------------------------------- #
# Étapes
# --------------------------------------------------------------------------- #
def _parse_form(raw: Any) -> InvestorForm:
    try:
        return InvestorForm.model_validate(raw)
    except ValidationError as exc:
        details = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise PipelineError("invalid_form", "Le formulaire est invalide.", details) from exc


def _user_constraints(raw: list[Any], market: Market) -> list[Constraint]:
    try:
        items = [Constraint.model_validate(c) for c in raw]
    except ValidationError as exc:
        raise PipelineError("invalid_constraints", "Contraintes invalides.", [e["msg"] for e in exc.errors()]) from exc
    valid, errors = validate_all(items, market.allowed_values())
    if errors:
        raise PipelineError("invalid_constraints", "Certaines contraintes sont hors catalogue.", errors)
    return valid


def promote_profile_defaults(constraints: list[Constraint]) -> list[Constraint]:
    """Contraintes données à l'optimiseur: celles de l'utilisateur, plus les défauts du profil promus en contraintes
    dures tant qu'ils ne créent pas de conflit."""
    promoted = [c for c in constraints if c.source != "profile"]
    for c in constraints:
        if c.source == "profile":
            candidate = promoted + [c.model_copy(update={"hard": True})]
            if not detect_conflicts(candidate):
                promoted = candidate
    return promoted


async def _resolve_constraints(
    payload: dict, bus: EventBus, market: Market
) -> Optional[tuple[InvestorForm, list[Constraint]]]:
    """Étapes 1 à 3c. Retourne None si le pipeline doit s'arrêter pour clarification."""
    mode = payload.get("mode", "initial")

    if mode == "initial":
        form = _parse_form(payload.get("form"))
        constraints = _user_constraints([c.model_dump() for c in form.constraints], market)
        conflicts = detect_conflicts(constraints)
        if conflicts:
            bus.emit("clarification", step="3", agent="Orchestrateur", questions=conflicts, understood=[])
            return None
        bus.emit("status", step="3", agent="Orchestrateur", state="done", text="Formulaire reçu")
        return form, constraints

    if mode != "refine":
        raise PipelineError("invalid_request", "Le champ `mode` doit valoir « initial » ou « refine ».")

    context = payload.get("context") or {}
    form = _parse_form(context.get("form"))
    current = _user_constraints(context.get("constraints", []), market)
    message = str(payload.get("message", "")).strip()[:MAX_MESSAGE_CHARS]
    if not message:
        raise PipelineError("invalid_request", "Le message est vide.")

    bus.emit("status", step="3", agent="Orchestrateur", state="done", text="Relance avec de nouvelles contraintes")
    outcome = await run_extraction_agent(bus, market, message, current)
    understood = [describe(c) for c in outcome.constraints]
    if outcome.needs_clarification:
        bus.emit("clarification", step="3b", agent="Extraction", questions=outcome.questions, understood=understood)
        return None

    merged = merge_constraints(current, outcome.constraints, outcome.removals)
    conflicts = detect_conflicts(merged)
    if conflicts:
        bus.emit("clarification", step="3c", agent="Fusion", questions=conflicts, understood=understood)
        return None
    bus.emit(
        "status", step="3c", agent="Fusion", state="done",
        text="Contraintes mises à jour", added=understood, removed=[f"{r.type.value} {r.target or ''}".strip() for r in outcome.removals],
    )
    return form, merged


async def _build_portfolios(
    bus: EventBus, market: Market, profile: InvestorProfile, pm_constraints: list[Constraint],
    feedback: dict[str, str],
) -> list[Portfolio]:
    async def one(mandate: Mandate) -> Portfolio:
        try:
            return await run_portfolio_manager(bus, market, mandate, profile, pm_constraints, feedback.get(mandate.id))
        except Exception as exc:  # noqa: BLE001
            logger.exception("PM %s en échec", mandate.id)
            return Portfolio(id=mandate.id, mandate=mandate.name, mandate_description=mandate.description,
                             status="failed", failure_reason=f"{type(exc).__name__}")

    return list(await asyncio.gather(*(one(m) for m in MANDATES)))


async def _judge_portfolios(
    bus: EventBus, market: Market, profile: InvestorProfile, portfolios: list[Portfolio]
) -> dict[str, JudgeVerdict]:
    async def one(p: Portfolio) -> tuple[str, JudgeVerdict]:
        try:
            return p.id, await run_judge(bus, market, profile, p, profile.constraints)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Juge %s en échec", p.id)
            bus.emit("status", step="8", agent=f"Juge {p.mandate}", state="warning",
                     text="Avis qualitatif indisponible, conformité vérifiée par le système")
            checks = evaluate(market, {x.symbol: x.weight for x in p.positions}, profile.constraints)
            hard = sum(1 for c in checks if c.constraint.hard and not c.passed)
            soft = sum(1 for c in checks if not c.constraint.hard and not c.passed)
            return p.id, JudgeVerdict(
                portfolio_id=p.id, compliant=hard == 0, hard_violations=hard, soft_violations=soft,
                checks=checks, fit_score=0, comment=f"Avis indisponible ({type(exc).__name__}).",
            )

    ok = [p for p in portfolios if p.status == "ok"]
    return dict(await asyncio.gather(*(one(p) for p in ok)))


def _feedback(portfolios: list[Portfolio], verdicts: dict[str, JudgeVerdict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in portfolios:
        v = verdicts.get(p.id)
        if p.status == "failed":
            out[p.id] = f"Aucun portefeuille n'a pu être construit: {p.failure_reason}"
        elif v and not v.compliant:
            lines = [f"- {c.label}: {c.message}" for c in v.checks if c.constraint.hard and not c.passed]
            out[p.id] = "\n".join(lines + [f"- Correction suggérée: {f}" for f in v.suggested_fixes])
    return out


async def run_pipeline(payload: dict, bus: EventBus) -> None:
    settings = get_settings()
    market = await asyncio.to_thread(get_market)

    resolved = await _resolve_constraints(payload, bus, market)
    if resolved is None:
        return
    form, user_constraints = resolved

    # Étape 4: profil
    assessment = await run_profile_agent(bus, form, user_constraints)
    profile = assemble_profile(form, user_constraints, assessment)
    bus.emit("profile", step="4", agent="Profil", data=profile.model_dump(mode="json"),
             labels=[describe(c) for c in profile.constraints])
    pm_constraints = promote_profile_defaults(profile.constraints)

    # Étapes 5 à 8: portefeuilles puis juges, avec un nombre limité de nouveaux essais
    bus.emit("status", step="5", agent="Orchestrateur", state="start", text="Lancement des 3 gestionnaires en parallèle")
    portfolios = await _build_portfolios(bus, market, profile, pm_constraints, {})
    verdicts = await _judge_portfolios(bus, market, profile, portfolios)

    retries = 0
    while not any(v.compliant for v in verdicts.values()) and retries < settings.max_pm_retries:
        retries += 1
        bus.emit("status", step="8", agent="Orchestrateur", state="retry",
                 text=f"Aucun portefeuille conforme. Nouvel essai {retries}/{settings.max_pm_retries}")
        portfolios = await _build_portfolios(bus, market, profile, pm_constraints, _feedback(portfolios, verdicts))
        verdicts = await _judge_portfolios(bus, market, profile, portfolios)

    # Étape 9: CRO, seulement si au moins un portefeuille est conforme
    compliant = any(v.compliant for v in verdicts.values())
    report: Optional[RiskReport] = None
    if compliant:
        try:
            report = await run_cro(bus, profile, portfolios, verdicts)
        except AgentError:
            bus.emit("status", step="9", agent="CRO", state="warning", text="Rapport de risque indisponible")
    else:
        bus.emit("status", step="9", agent="CRO", state="skipped",
                 text="Aucun portefeuille conforme: rapport de risque non produit")

    # Étape 10: assemblage
    bus.emit(
        "result",
        step="10",
        agent="Orchestrateur",
        data={
            "profile": profile.model_dump(mode="json"),
            "constraint_labels": [describe(c) for c in profile.constraints],
            "portfolios": [
                {
                    "portfolio": p.model_dump(mode="json"),
                    "verdict": verdicts[p.id].model_dump(mode="json") if p.id in verdicts else None,
                }
                for p in portfolios
            ],
            "risk_report": report.model_dump(mode="json") if report else None,
            "no_compliant_portfolio": not compliant,
            "context": {  # à renvoyer tel quel par le frontend lors d'une relance
                "form": form.model_dump(mode="json", exclude={"constraints"}),
                "constraints": [c.model_dump(mode="json") for c in user_constraints],
            },
        },
    )
