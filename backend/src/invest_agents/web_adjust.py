"""Chat d'ajustement du frontend (« Ajuster avec Pépite »), version backend de `proposeAdjustment` (api.ts).

Requête:
    {"mode": "adjust", "portfolio": "equilibre", "message": "plus de tech",
     "profile": {...}, "constraints": {...},          # préférences en vigueur pour ce portefeuille
     "current": Portfolio}                            # portefeuille affiché (valeurs « avant »)

Le flux se termine par:
    {"type": "adjust", "proposal": AdjustProposal & {"portfolio": Portfolio | null}}
    {"type": "done"}

`proposal.patch` et `proposal.riskShift` ont le format du frontend: s'il applique l'ajustement, il remplace
le portefeuille par `proposal.portfolio` au lieu de le recalculer avec engine.ts.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from .agents.base import AgentError, run_agent
from .agents.profile import assemble_profile
from .contract import (
    CLASS_LABELS, FACTOR_LABELS, REGION_LABELS, THEME_LABELS, FrontendConstraints, FrontendProfile,
    global_exclusions, make_feasible, mandate_constraints, risk_score, to_frontend_portfolio, to_investor_form,
)
from .data import get_market
from .events import EventBus
from .mandates import MANDATE_BY_ID, vol_cap_for
from .web_pipeline import Plan, _build, _judge, assess, dedupe

logger = logging.getLogger(__name__)

BLOCK_LABELS = {"classes": CLASS_LABELS, "regions": REGION_LABELS, "themes": THEME_LABELS, "factors": FACTOR_LABELS}
BLOCK_DIMENSION = {"regions": "region", "themes": "theme", "factors": "factor"}


class AdjustRequest(BaseModel):
    portfolio: Literal["prudent", "equilibre", "conviction"]
    message: str = Field(min_length=1, max_length=1000)
    profile: FrontendProfile
    constraints: FrontendConstraints = FrontendConstraints()
    current: Optional[dict] = None


class PatchItem(BaseModel):
    block: Literal["classes", "regions", "themes", "factors"]
    id: str = Field(description="Identifiant exact de l'élément dans le catalogue")
    level: Literal[-2, -1, 0, 1, 2] = Field(description="-2 Exclure, -1 Moins, 0 Neutre, 1 Plus, 2 Imposer")


class AdjustIntent(BaseModel):
    """Lecture de la demande du client."""

    understood: bool = Field(description="False si la demande ne correspond à aucun élément du catalogue")
    patch: list[PatchItem] = Field(default_factory=list)
    risk_shift: int = Field(default=0, ge=-30, le=30,
                            description="Décalage du score de risque: négatif pour « moins de risque », positif pour « plus de risque »")
    reply: str = Field(description="Réponse de Pépite au client, 1 à 2 phrases, tutoiement, sans chiffres")


SYSTEM = """Tu es Pépite, la mascotte de MonPort. Le client demande un ajustement de son portefeuille « {name} ».
Traduis sa demande en changements sur l'échelle de préférences: -2 Exclure, -1 Moins, 0 Neutre, 1 Plus, 2 Imposer.

CATALOGUE (bloc: identifiant = libellé):
{catalog}

RÈGLES
- « plus de X » = 1, « beaucoup plus », « surtout » ou « je veux du X » = 2, « moins de X » = -1,
  « pas de X », « sans X », « je ne veux pas de X » = -2, « peu importe X » = 0.
- Compare avec les préférences actuelles: si « plus de X » vise un élément déjà à 1, passe-le à 2; si « moins de X »
  vise un élément déjà à -1, passe-le à -2 seulement si le client dit « pas de » ou « sans ».
- Les « énergies fossiles », le « pétrole » et le « gaz » correspondent au thème `fossiles`.
- « Moins de risque », « plus prudent », « plus stable »: aucun patch obligatoire, mets risk_shift à -15.
  « Plus de risque », « plus audacieux »: risk_shift à 15.
- Si la demande ne correspond à rien du catalogue, mets understood à false et propose dans `reply` des exemples
  (« plus de tech », « pas de pétrole », « moins de risque »).
- `reply` annonce ce que tu vas faire, sans chiffres: ils seront calculés ensuite."""


def _reply(bus: EventBus, text: str) -> None:
    """Réponse sans changement (demande incomprise, déjà en place ou irréalisable)."""
    bus.emit("fe", event={"type": "adjust", "proposal": {"reply": text, "changes": [], "portfolio": None}})
    bus.emit("fe", event={"type": "done"})


def _catalog() -> str:
    return "\n".join(f"- {block}: " + ", ".join(f"{k} = {v}" for k, v in labels.items())
                     for block, labels in BLOCK_LABELS.items())


def _apply(fc: FrontendConstraints, patch: list[PatchItem]) -> FrontendConstraints:
    data = fc.model_dump()
    for item in patch:
        if item.id in BLOCK_LABELS[item.block]:
            data[item.block][item.id] = item.level
    return FrontendConstraints.model_validate(data)


def _group_weight(market, holdings: list[dict], dim: str, target: str) -> float:
    inside = market.members(dim, target)
    return round(sum(h["weight"] for h in holdings if bool(inside.get(h["ticker"], False))), 4)


def _changes(market, before: Optional[dict], after: dict, patch: list[PatchItem]) -> list[dict]:
    if not before:
        return []
    rows = []
    for k, label in CLASS_LABELS.items():
        b, a = before.get("allocation", {}).get(k, 0.0), after["allocation"].get(k, 0.0)
        if abs(a - b) >= 0.005:
            rows.append({"label": label, "before": b, "after": a})
    for item in patch:
        dim = BLOCK_DIMENSION.get(item.block)
        if dim:
            label = BLOCK_LABELS[item.block][item.id]
            b = _group_weight(market, before.get("holdings", []), dim, item.id)
            a = _group_weight(market, after["holdings"], dim, item.id)
            if abs(a - b) >= 0.001:
                rows.append({"label": label, "before": b, "after": a})
    for key, label in (("expectedReturn", "Rendement attendu"), ("volatility", "Volatilité")):
        b, a = before.get("metrics", {}).get(key), after["metrics"][key]
        if b is not None and abs(a - b) >= 0.001:
            rows.append({"label": label, "before": b, "after": a})
    return rows


async def run_adjust(payload: dict, bus: EventBus) -> None:
    req = AdjustRequest.model_validate(payload)
    market = await asyncio.to_thread(get_market)
    md = MANDATE_BY_ID[req.portfolio]
    score = risk_score(req.profile)

    intent = await run_agent(
        bus=bus, label="Pépite", step="3b", kind="fast",
        system_prompt=SYSTEM.format(name=md.name, catalog=_catalog()),
        user_prompt=f"Préférences actuelles: {json.dumps(req.constraints.model_dump(), ensure_ascii=False)}\n\n"
                    f"Demande du client: « {req.message} »",
        schema=AdjustIntent, start_text="Pépite lit ta demande…", done_text="Demande comprise",
    )
    if not intent.understood or (not intent.patch and intent.risk_shift == 0):
        _reply(bus, intent.reply)
        return
    current = req.constraints.model_dump()
    valid = [i for i in intent.patch if i.id in BLOCK_LABELS[i.block]]
    intent.patch = [i for i in valid if current[i.block].get(i.id, 0) != i.level]
    already = [BLOCK_LABELS[i.block][i.id] for i in valid if i not in intent.patch]
    if not intent.patch and intent.risk_shift == 0:
        _reply(bus, f"C’est déjà le cas dans le portefeuille {md.name} : rien à changer.")
        return
    if already:
        intent.reply += f" ({', '.join(already)} : c’était déjà en place.)"

    fc = _apply(req.constraints, intent.patch)
    new_score = max(5, min(95, score + intent.risk_shift))
    form = to_investor_form(req.profile)
    exclusions = global_exclusions(fc)
    assessment = await assess(bus, form, exclusions)
    profile = assemble_profile(form, exclusions, assessment)

    stock_cap = max(0.05, min(0.15, assessment.suggested_max_position_weight))
    cons, notes = mandate_constraints(md, new_score, fc, market, stock_cap)
    cap = vol_cap_for(md, assessment.suggested_max_volatility * (1 + intent.risk_shift / 100))
    cons, more, cap = await asyncio.to_thread(make_feasible, market, md, cons, cap)
    plan = Plan(md, cons, notes + more, cap)
    portfolio = await _build(bus, market, profile, plan, None)
    if portfolio.status != "ok":
        _reply(bus, "Je n’arrive pas à construire ce portefeuille avec cette demande. Essaie autre chose?")
        return
    verdict = await _judge(bus, market, profile, portfolio, plan)

    warnings = []
    if not verdict.compliant:
        warnings += [f"Limite non respectée : {c.label}." for c in verdict.checks if c.constraint.hard and not c.passed]
    riskier = intent.risk_shift > 0 or any(i.level > 0 and i.id in ("crypto", "actions") for i in intent.patch)
    warning = ("ça augmente ton risque au-delà de ton profil. Tu peux quand même l’appliquer, c’est ton choix."
               if riskier and score < 50 else None)
    after = to_frontend_portfolio(market, md, portfolio, new_score, warnings, plan.notes)
    after["agentNotes"].append(f"Ajustement demandé : {req.message}.")

    patch: dict[str, dict] = {}
    for item in intent.patch:
        patch.setdefault(item.block, {})[item.id] = item.level
    proposal = {"reply": intent.reply, "changes": _changes(market, req.current, after, intent.patch),
                "patch": patch, "riskShift": intent.risk_shift, "portfolio": after}
    if warning:
        proposal["warning"] = warning
    bus.emit("fe", event={"type": "adjust", "proposal": proposal})
    bus.emit("fe", event={"type": "done"})


async def stream_adjust(payload: dict) -> AsyncIterator[dict]:
    bus = EventBus()

    async def worker() -> None:
        try:
            await run_adjust(payload, bus)
        except ValidationError as exc:
            details = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
            bus.emit("error", code="invalid_request", message=f"Requête invalide: {details}")
        except AgentError as exc:
            bus.emit("error", code="agent_error", message=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Erreur dans l'ajustement")
            bus.emit("error", code="internal", message=f"Erreur interne ({type(exc).__name__}).")
        finally:
            bus.close()

    task = asyncio.create_task(worker())
    async for out in dedupe(bus.stream(task)):
        yield out
