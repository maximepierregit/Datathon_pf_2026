"""Pont entre le frontend MonPort et le pipeline.

Le frontend envoie son profil et ses préférences (échelle −2 à +2) et attend ses propres événements
(`frontend/src/types.ts`, `PipelineEvent`): une carte par agent (Profil, 3 gestionnaires, 3 juges,
responsable des risques), les messages de Pépite, puis les 3 portefeuilles au format `Portfolio`.

    {"mode": "monport", "profile": {...}, "constraints": {...}}

Ce module traduit dans les deux sens sans toucher au pipeline: l'entrée devient un `InvestorForm`,
les événements du bus deviennent des `PipelineEvent`. Tous les textes visibles sont tutoyés.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Iterable, Optional

from pydantic import ValidationError

from .constraints import excluded_mask
from .data import Market, get_market
from .mandates import MANDATES
from .orchestrator import stream_pipeline
from .schemas import Constraint, ConstraintType as T, InvestorForm

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Vocabulaire du frontend
# --------------------------------------------------------------------------- #
PORTFOLIO_IDS = {"pm1": "prudent", "pm2": "equilibre", "pm3": "conviction"}
PORTFOLIO_NAMES = {"prudent": "Prudent", "equilibre": "Équilibré", "conviction": "Conviction"}
MANDATE_TO_FRONT = {m.name: PORTFOLIO_IDS[m.id] for m in MANDATES}
CLASSES = ["actions", "obligations", "immobilier", "or", "crypto", "liquidites"]

# Valeurs possibles dans le dataset (synthétique et réel). Seules celles présentes servent.
CLASS_TARGETS = {
    "actions": ["Equity", "Equities"],
    "obligations": ["Fixed Income", "Bonds"],
    "immobilier": ["Real Estate"],
    "or": ["Commodities", "Commodity"],
    "crypto": ["Crypto", "Alternative"],
    "liquidites": ["Money Market", "Cash"],
}
REGION_COUNTRIES = {
    "canada": ["Canada"],
    "usa": ["United States"],
    "europe": ["France", "Germany", "United Kingdom", "Netherlands", "Switzerland", "Spain", "Italy", "Ireland",
               "Sweden", "Denmark", "Belgium", "Finland", "Norway"],
    "asie": ["Japan", "Australia", "Hong Kong", "Singapore", "New Zealand", "South Korea", "Taiwan"],
    "emergents": ["China", "India", "Brazil", "Mexico", "South Africa", "Indonesia", "Thailand"],
}
THEME_SECTORS = {
    "tech": ["Technology", "Information Technology"],
    "sante": ["Health Care"],
    "fossiles": ["Energy"],
    "finance": ["Financials"],
    "immobilier": ["Real Estate"],
    "consommation": ["Consumer Staples", "Consumer Discretionary"],
    "industrie": ["Industrials"],
}
BLOCK_LABELS = {"classes": "classe", "regions": "région", "themes": "thématique", "factors": "facteur"}

# Poids associés à chaque niveau: (Moins = plafond souple, Plus = plancher souple, Imposer = plancher dur)
LEVEL_WEIGHTS = {"classes": (0.25, 0.15, 0.10), "regions": (0.10, 0.10, 0.05), "themes": (0.10, 0.10, 0.05)}
DIMENSION_TYPES = {
    "classes": (T.EXCLUDE_ASSET_CLASS, T.MAX_ASSET_CLASS_WEIGHT, T.MIN_ASSET_CLASS_WEIGHT),
    "regions": (T.EXCLUDE_COUNTRY, T.MAX_COUNTRY_WEIGHT, T.MIN_COUNTRY_WEIGHT),
    "themes": (T.EXCLUDE_SECTOR, T.MAX_SECTOR_WEIGHT, T.MIN_SECTOR_WEIGHT),
}

LOSS_BY_REACTION = {0: 10.0, 1: 15.0, 2: 25.0, 3: 35.0}  # baisse de 20 %: je vends tout … j'investis plus
OBJECTIVES = {"securiser": "preservation", "fructifier": "balanced", "viser-haut": "growth"}
EXPERIENCE = {1: "none", 2: "basic", 3: "intermediate", 4: "advanced", 5: "advanced"}
FEES = {"ETF": 0.002}  # faute de donnée: 0,20 % par FNB, rien pour un titre détenu en direct


# --------------------------------------------------------------------------- #
# Entrée: profil et préférences -> InvestorForm
# --------------------------------------------------------------------------- #
def _targets(block: str, item: str, allowed: dict[str, list[str]]) -> list[str]:
    candidates = {"classes": CLASS_TARGETS, "regions": REGION_COUNTRIES, "themes": THEME_SECTORS}[block].get(item, [])
    dimension = {"classes": "asset_class", "regions": "country", "themes": "sector"}[block]
    present = {v.lower(): v for v in allowed[dimension]}
    return [present[c.lower()] for c in candidates if c.lower() in present]


def preference_constraints(prefs: dict, allowed: dict[str, list[str]]) -> tuple[list[Constraint], list[str]]:
    """Traduit l'échelle Exclure … Imposer en contraintes du catalogue. Retourne aussi ce qui n'a pas pu l'être."""
    out: list[Constraint] = []
    skipped: list[str] = []
    for block, (exclude, cap, floor) in DIMENSION_TYPES.items():
        moins, plus, impose = LEVEL_WEIGHTS[block]
        for item, level in (prefs.get(block) or {}).items():
            if not level:
                continue
            targets = _targets(block, item, allowed)
            # Une région de plusieurs pays ne s'exprime qu'en exclusion: les poids sont par pays.
            if not targets or (level != -2 and len(targets) > 1 and block == "regions"):
                skipped.append(f"{BLOCK_LABELS[block]} « {item} »")
                continue
            for t in targets[:1] if level > 0 else targets:
                note = f"MonPort: {block}.{item} = {level}"
                if level == -2:
                    out.append(Constraint(type=exclude, target=t, hard=True, note=note))
                elif level == -1:
                    out.append(Constraint(type=cap, target=t, value=moins, hard=False, note=note))
                else:
                    out.append(Constraint(type=floor, target=t, value=impose if level == 2 else plus,
                                          hard=level == 2, note=note))
    skipped += [f"facteur « {f} »" for f, level in (prefs.get("factors") or {}).items() if level]

    # FNB seulement: aucun titre détenu en direct (actions individuelles, crypto au comptant).
    if prefs.get("vehicles") == "fnb":
        for t in ("Equity", "Crypto", "Alternative"):
            if t.lower() in {v.lower() for v in allowed["asset_class"]}:
                out.append(Constraint(type=T.EXCLUDE_ASSET_CLASS, target=t, hard=True, note="MonPort: FNB seulement"))

    # Une exclusion l'emporte sur un poids visé (ex.: FNB seulement et « Imposer » les actions).
    excluded = {(c.type.value.removeprefix("exclude_"), (c.target or "").lower()) for c in out
                if c.type.value.startswith("exclude_")}
    unique: dict[tuple[str, str], Constraint] = {}
    for c in out:
        dimension = c.type.value.removeprefix("min_").removeprefix("max_").removesuffix("_weight")
        if not c.type.value.startswith("exclude_") and (dimension, (c.target or "").lower()) in excluded:
            continue
        # Une même cible peut venir de deux blocs (immobilier): on garde la contrainte la plus forte.
        key = (c.type.value, (c.target or "").lower())
        if key not in unique or (c.hard and not unique[key].hard):
            unique[key] = c
    return list(unique.values()), skipped


def to_form(profile: dict, prefs: dict, market: Market) -> tuple[InvestorForm, list[str]]:
    reaction = int(profile.get("lossReaction", 2))
    objective = OBJECTIVES.get(str(profile.get("objective")), "balanced")
    horizon = int(profile.get("horizon", 10))
    constraints, skipped = preference_constraints(prefs, market.allowed_values())
    form = InvestorForm(
        age=min(110, max(18, int(profile.get("age", 35)))),
        investment_amount_cad=float(profile.get("amount", 10000)),
        horizon_years=min(60, max(1, horizon)),
        risk_tolerance=min(5, 1 + reaction + (1 if objective == "growth" else 0)),
        max_acceptable_loss_pct=LOSS_BY_REACTION.get(reaction, 25.0),
        objective=objective,
        experience=EXPERIENCE.get(int(profile.get("comfort", 3)), "intermediate"),
        liquidity_needs="high" if horizon < 3 else "medium" if horizon < 7 else "low",
        constraints=constraints,
    )
    return form, skipped


# --------------------------------------------------------------------------- #
# Sortie: résultat du pipeline -> Portfolio du frontend
# --------------------------------------------------------------------------- #
def front_class(row: Any) -> str:
    """Classe du frontend pour un titre: le type d'instrument d'abord, puis la catégorie ou le nom du FNB."""
    instrument = str(row.get("instrument_type", "")).lower()
    if instrument == "stock":
        return "actions"
    if instrument == "cryptocurrency":
        return "crypto"
    text = f"{row.get('asset_class', '')} {row.get('name', '')}".lower()
    for cls, words in (
        ("obligations", ("fixed income", "bond", "oblig")),
        ("immobilier", ("real estate", "reit", "immobil")),
        ("or", ("commodit", "gold", " or ")),
        ("crypto", ("crypto", "bitcoin", "ether")),
        ("liquidites", ("money market", "cash", "monétaire")),
    ):
        if any(w in text for w in words):
            return cls
    return "actions"


def _rename(text: str) -> str:
    """Les agents nomment les mandats; le client voit les noms MonPort."""
    for mandate, front in MANDATE_TO_FRONT.items():
        text = text.replace(mandate, PORTFOLIO_NAMES[front])
    return text


def to_portfolio(item: dict, market: Market, risk_report: Optional[dict], risk_score: int,
                 notes: list[str]) -> dict:
    p, verdict = item["portfolio"], item.get("verdict") or {}
    front_id = PORTFOLIO_IDS[p["id"]]
    holdings, allocation, fees = [], {c: 0.0 for c in CLASSES}, 0.0
    for pos in p["positions"]:
        row = market.assets.loc[pos["symbol"]] if pos["symbol"] in market.assets.index else pos
        cls = front_class(row)
        holdings.append({"ticker": pos["symbol"], "name": pos["name"], "assetClass": cls, "weight": pos["weight"]})
        allocation[cls] += pos["weight"]
        fees += pos["weight"] * FEES.get(str(row.get("instrument_type", "")), 0.0)

    m = p.get("metrics") or {}
    mu, sigma = m.get("expected_return", 0.0), m.get("volatility", 0.0)
    warnings = [
        _rename(f"{w['title']}. {w['detail']}")
        for w in (risk_report or {}).get("warnings", [])
        if w.get("portfolio_id") == p["id"] and w.get("severity") in ("medium", "high")
    ]
    agent_notes = [_rename(t) for t in (p.get("summary"), p.get("tradeoffs"), verdict.get("comment")) if t]
    if notes:
        agent_notes.append(f"Pas encore pris en compte par les agents : {', '.join(notes)}.")
    if verdict and not verdict.get("compliant", True):
        warnings.insert(0, "Ce portefeuille ne respecte pas toutes tes limites. Lis les détails avant de le choisir.")
    elif verdict:
        agent_notes.append("Le juge confirme que ce portefeuille respecte tes limites.")
    return {
        "id": front_id,
        "riskScore": min(95, max(5, risk_score * 10)),
        "holdings": holdings,
        "allocation": {k: round(v, 4) for k, v in allocation.items()},
        # Mêmes formules que metricsOf() dans frontend/src/lib/engine.ts, sur les chiffres de l'optimiseur.
        "metrics": {
            "expectedReturn": mu,
            "volatility": sigma,
            "worstYear": mu - 2.33 * sigma,
            "fees": round(fees, 5),
            "sharpe": m.get("sharpe", 0.0),
            "maxDrawdown": m.get("max_drawdown", 0.0),
            "var95": -(mu - 1.645 * sigma),
            "es95": -(mu - 2.063 * sigma),
        },
        "warnings": warnings,
        "agentNotes": agent_notes,
    }


# --------------------------------------------------------------------------- #
# Événements: bus du pipeline -> PipelineEvent
# --------------------------------------------------------------------------- #
TOOL_TEXT = {
    "describe_universe": "tour d’horizon des placements",
    "screen_assets": "recherche de placements",
    "optimize_portfolio": "calcul des poids",
}


def _status(agent: str, status: str, message: str) -> dict:
    return {"type": "agent_status", "agent": agent, "status": status, "message": message}


def _pepite(text: str) -> dict:
    return {"type": "pepite", "text": text}


class Translator:
    """Un agent du pipeline = une carte du frontend: profil, gestionnaire-<id>, juge-<id>, risques."""

    def __init__(self, market: Market, form: InvestorForm, skipped: list[str]) -> None:
        self.market, self.form, self.skipped = market, form, skipped

    def _card(self, agent: str, prefix: str) -> Optional[str]:
        """« PM Défensif » -> « gestionnaire-prudent »."""
        front = MANDATE_TO_FRONT.get(agent.removeprefix(prefix).strip())
        return f"{'gestionnaire' if prefix == 'PM' else 'juge'}-{front}" if front else None

    def translate(self, e: dict) -> Iterable[dict]:
        kind, agent, state = e.get("type"), e.get("agent") or "", e.get("state")
        pm = self._card(agent, "PM") if agent.startswith("PM ") else None
        judge = self._card(agent, "Juge") if agent.startswith("Juge ") else None
        if kind == "heartbeat":
            yield {"type": "heartbeat"}
        elif kind == "status" and agent == "Profil" and state == "start":
            yield _status("profil", "running", "Lecture de ton profil et de tes préférences…")
        elif kind == "profile":
            hard = [c for c in self.form.constraints if c.hard]
            before = len(self.market.assets)
            after = int((~excluded_mask(self.market, hard)).sum())
            yield {"type": "universe", "before": before, "after": after}
            yield _status("profil", "done", f"{after} placements retenus sur {before}.")
        elif pm and kind == "status" and state == "start":
            yield _status(pm, "running", "Construction du portefeuille…")
        elif pm and kind == "tool" and e.get("name") in TOOL_TEXT:
            yield _status(pm, "running", f"{TOOL_TEXT[e['name']].capitalize()}…")
        elif pm and kind == "status" and state == "warning":
            yield _status(pm, "running", "Sélection de secours en cours…")
        elif pm and kind == "status" and state == "done":
            yield _status(pm, "done", "Portefeuille prêt.")
        elif judge and kind == "status" and state == "start":
            yield _status(judge, "running", "Vérification de tes limites…")
        elif judge and kind == "status" and state in ("done", "warning"):
            yield _status(judge, "done", "Évaluation terminée.")
        elif kind == "status" and state == "retry":
            yield _pepite("Oh! Les juges renvoient les portefeuilles aux gestionnaires.")
            for front in PORTFOLIO_NAMES:
                yield _status(f"juge-{front}", "pending", "")
                yield _status(f"gestionnaire-{front}", "running", "Nouvel essai avec les remarques du juge…")
        elif kind == "status" and agent == "CRO" and state == "start":
            yield _status("risques", "running", "Recherche des incohérences avec ton profil…")
        elif kind == "clarification":
            yield {"type": "error", "message": " ".join(e.get("questions") or ["Tes préférences se contredisent."])}
        elif kind == "error":
            yield {"type": "error", "message": e.get("message") or "Erreur du pipeline."}
        elif kind == "result":
            yield from self._result(e["data"])

    def _result(self, data: dict) -> Iterable[dict]:
        report = data.get("risk_report")
        # Seulement les incohérences graves: les autres sont écrites pour un conseiller, pas pour le client.
        for issue in (report or {}).get("profile_inconsistencies", []):
            if issue.get("severity") == "high":
                yield {"type": "warning", "text": _rename(issue["detail"])}
        score = data["profile"]["assessment"]["risk_score"]
        portfolios = {
            PORTFOLIO_IDS[item["portfolio"]["id"]]: to_portfolio(item, self.market, report, score, self.skipped)
            for item in data["portfolios"]
            if item["portfolio"]["status"] == "ok"
        }
        if portfolios:
            yield {"type": "portfolios", "portfolios": portfolios}
        # Bilan de chaque juge: la conformité est calculée par le code (JudgeVerdict.compliant).
        for item in data["portfolios"]:
            verdict, card = item.get("verdict"), f"juge-{PORTFOLIO_IDS[item['portfolio']['id']]}"
            if verdict is None:
                yield _status(card, "done", "Pas de portefeuille à vérifier.")
            elif verdict["compliant"]:
                yield _status(card, "done", "Toutes tes limites sont respectées.")
            else:
                yield _status(card, "done", f"{verdict['hard_violations']} limite(s) non respectée(s).")
        if report is None:
            yield _status("risques", "done", "Pas de rapport : aucun portefeuille ne respecte toutes tes limites.")
        else:
            n = sum(1 for w in report.get("warnings", []) if w.get("severity") in ("medium", "high"))
            yield _status("risques", "done", f"{n} mise(s) en garde à lire." if n else "Rien de particulier à signaler.")
        yield _pepite("Voilà! Trois propositions t’attendent. C’est toi qui choisis.")
        yield {"type": "done"}


# --------------------------------------------------------------------------- #
# Point d'entrée
# --------------------------------------------------------------------------- #
async def stream_monport(payload: dict) -> AsyncIterator[dict]:
    market = await asyncio.to_thread(get_market)
    try:
        form, skipped = to_form(payload.get("profile") or {}, payload.get("constraints") or {}, market)
    except (ValidationError, TypeError, ValueError) as exc:
        logger.warning("Profil MonPort invalide: %s", exc)
        yield {"type": "error", "message": "Ton profil est incomplet. Reprends le questionnaire."}
        return

    yield _pepite("C’est parti! Mes agents se mettent au travail.")
    translator = Translator(market, form, skipped)
    async for event in stream_pipeline({"mode": "initial", "form": form.model_dump(mode="json")}):
        for out in translator.translate(event):
            yield out
