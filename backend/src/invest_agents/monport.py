"""Pont entre le frontend MonPort et les agents.

Deux appels, un par écran (`frontend/src/api.ts`):

    {"mode": "monport_check", "profile": {...}, "constraints": {...}}
        Pépite lit le questionnaire (JSON) et juge sa cohérence -> {"type": "check", "check": PepiteCheck}

    {"mode": "monport", "profile": ..., "constraints": ..., "check": PepiteCheck, "adjustment": "texte libre"}
        Pépite écrit 3 profils de contraintes (JSON) -> 3 gestionnaires en parallèle -> 3 juges
        profil incohérent: 3 portefeuilles, « Tes contraintes » et deux mélanges 80/20 calculés par le code
        profil cohérent:   le juge final désigne un seul portefeuille
        -> responsable des risques (CRO) -> {"type": "portfolios"}

Les événements suivent `PipelineEvent` de `frontend/src/types.ts`: une carte par agent. Le pipeline de
`orchestrator.py` n'est pas utilisé ici, seulement ses agents, l'optimiseur et `constraints`.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any, AsyncIterator, Awaitable, Callable, Iterable, Optional

from pydantic import ValidationError

from .agents.base import AgentError
from .agents.cro import run_cro
from .agents.final_judge import run_final_judge
from .agents.judge import run_judge
from .agents.pepite import run_check, run_plan
from .agents.portfolio_manager import run_portfolio_manager
from .config import get_settings
from .constraints import DIMENSION_COLUMN, detect_conflicts, evaluate, excluded_mask, validate_all
from .data import Market, get_market
from .events import EventBus
from .mandates import Mandate
from .optimizer import optimize
from .schemas import (
    CoherenceIssue,
    Constraint,
    ConstraintPlan,
    ConstraintType as T,
    InvestorForm,
    InvestorProfile,
    JudgeVerdict,
    PepiteCheck,
    PepiteReview,
    Portfolio,
    Position,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Vocabulaire du frontend
# --------------------------------------------------------------------------- #
SLOTS = ["prudent", "equilibre", "conviction"]
CLASSES = ["actions", "obligations", "immobilier", "or", "crypto", "liquidites"]
CLASS_LABELS = {"actions": "Actions", "obligations": "Obligations", "immobilier": "Immobilier coté",
                "or": "Or et matières premières", "crypto": "Crypto-actifs", "liquidites": "Liquidités"}

# Profil incohérent: chaque gestionnaire construit une base…
BASE_NAMES = {"prudent": "Ton profil", "equilibre": "Tes contraintes", "conviction": "Tes préférences"}
# …et le client voit ces 3 portefeuilles (mêmes libellés que PORTFOLIO_META dans frontend/src/lib/engine.ts).
BLEND = 0.8
TRIO = {
    "prudent": ("Profil d’abord (80/20)", "80 % calé sur ton profil, 20 % sur tes préférences."),
    "equilibre": ("Tes contraintes", "Exactement ce que tu as demandé, même là où ça s’écarte de ton profil."),
    "conviction": ("Préférences d’abord (80/20)", "80 % calé sur tes préférences, 20 % sur ton profil."),
}
# Profil cohérent: trois variantes en concurrence, un seul gagnant présenté.
VARIANT_NAMES = {"prudent": "Variante prudente", "equilibre": "Variante fidèle", "conviction": "Variante audacieuse"}
WINNER_NAME = "Ton portefeuille"

# Libellés acceptés pour chaque élément du questionnaire. Seuls ceux présents dans le dataset servent.
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
DIRECT_CLASSES = ("Equity", "Crypto", "Alternative")  # titres détenus en direct, écartés par « FNB seulement »
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
LINE_CAP = 0.40  # limite de sécurité: aucune ligne au-delà de 40 %
MAX_ADJUSTMENT = 1000

# Répartition stratégique du profil (portefeuilles modèles 20/80 … 100/0): plancher d'obligations, fixé par le code
# pour les portefeuilles qui suivent le profil (« Ton profil », et les 3 variantes quand le profil est cohérent).
BOND_FLOOR = {"conservateur": 0.80, "modere": 0.60, "equilibre": 0.40, "dynamique": 0.20, "agressif": 0.0}
BOND_SHIFT = {"prudent": 0.10, "equilibre": 0.0, "conviction": -0.10}
BOND_TARGETS = ("Fixed Income", "Bonds")
CRYPTO_TARGETS = ("Crypto", "Alternative")
NO_CRYPTO = {"conservateur", "modere"}  # pas de crypto dans un portefeuille qui suit un profil prudent
PROFILE_NOTE = "Répartition du profil"

# Aversion au risque. Le questionnaire donne une position S (0 très prudent … 1 très audacieux), convertie en
# coefficient A (1 très audacieux … 25 très prudent) pour l'objectif moyenne-variance de l'optimiseur.
# Mêmes règles que riskPosition() et riskAversion() de frontend/src/lib/engine.ts.
OBJECTIVE_TOLERANCE = {"securiser": 0.0, "fructifier": 0.5, "viser-haut": 1.0}
CAPACITY_MARGIN = 0.125  # la tolérance ne dépasse pas la capacité de plus de 3 crans sur 24
ADJUSTMENT_STEP = 0.05  # un cran d'ajustement de Pépite (au plus 2 crans, une demi-catégorie)
# Une catégorie par tranche de 0,2 de S, bornes de A du tableau des profils (interpolation logarithmique).
AVERSION_ANCHORS = [(0.0, 25.0), (0.2, 14.0), (0.4, 7.0), (0.6, 3.5), (0.8, 1.5), (1.0, 1.0)]
VOL_ANCHORS = [(0.0, 0.06), (0.2, 0.08), (0.4, 0.11), (0.6, 0.14), (0.8, 0.18), (1.0, 0.25)]  # filet de sécurité
STOCK_ANCHORS = [(0.0, 0.07), (0.2, 0.09), (0.4, 0.11), (0.6, 0.13), (0.8, 0.17), (1.0, 0.22)]
RISK_LABELS = ["conservateur", "modere", "equilibre", "dynamique", "agressif"]  # très prudent … très audacieux
# Cohérent: trois variantes du même profil, à une demi-catégorie l'une de l'autre. Incohérent: « Ton profil » et
# « Tes contraintes » suivent le profil; « Tes préférences » l'ignore (meilleur rendement pour le risque).
SLOT_SHIFT = {"prudent": -0.1, "equilibre": 0.0, "conviction": 0.1}
GUIDANCE = {
    "min_volatility": "Cherche les variations les plus douces: FNB d'obligations, titres défensifs, actifs peu corrélés.",
    "max_sharpe": "Cherche le meilleur rendement pour le risque pris. Diversifie par secteur, pays et classe d'actifs.",
    "max_return": "Cherche le rendement le plus élevé sous le plafond de volatilité, sans concentrer le portefeuille.",
}


# --------------------------------------------------------------------------- #
# Entrée: profil et préférences -> InvestorForm
# --------------------------------------------------------------------------- #
def _targets(block: str, item: str, allowed: dict[str, list[str]]) -> list[str]:
    candidates = {"classes": CLASS_TARGETS, "regions": REGION_COUNTRIES, "themes": THEME_SECTORS}[block].get(item, [])
    dimension = {"classes": "asset_class", "regions": "country", "themes": "sector"}[block]
    present = {v.lower(): v for v in allowed[dimension]}
    return [present[c.lower()] for c in candidates if c.lower() in present]


def _dedupe(constraints: list[Constraint]) -> list[Constraint]:
    """Une exclusion l'emporte sur un poids visé (ex.: FNB seulement et « Imposer » les actions); pour une même cible,
    on garde la contrainte la plus forte."""
    excluded = {(c.type.value.removeprefix("exclude_"), (c.target or "").lower()) for c in constraints
                if c.type.value.startswith("exclude_")}
    unique: dict[tuple[str, str], Constraint] = {}
    for c in constraints:
        dimension = c.type.value.removeprefix("min_").removeprefix("max_").removesuffix("_weight")
        if not c.type.value.startswith("exclude_") and (dimension, (c.target or "").lower()) in excluded:
            continue
        key = (c.type.value, (c.target or "").lower())
        if key not in unique or (c.hard and not unique[key].hard):
            unique[key] = c
    return list(unique.values())


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

    if prefs.get("vehicles") == "fnb":
        present = {v.lower() for v in allowed["asset_class"]}
        out += [Constraint(type=T.EXCLUDE_ASSET_CLASS, target=t, hard=True, note="MonPort: FNB seulement")
                for t in DIRECT_CLASSES if t.lower() in present]
    return _dedupe(out), skipped


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
# Faits calculés: mêmes règles que riskScore() et coherenceWarnings() de frontend/src/lib/engine.ts
# --------------------------------------------------------------------------- #
def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return min(hi, max(lo, v))


def capacity(profile: dict) -> float:
    """Ce que le client peut se permettre: horizon et âge, de 0 à 1."""
    h = (min(float(profile.get("horizon", 10)), 20) - 1) / 19
    a = (75 - float(profile.get("age", 35))) / 50
    return 0.6 * _clamp(h) + 0.4 * _clamp(a)


def tolerance(profile: dict) -> float:
    """Ce que le client veut supporter: réaction à une baisse, objectif, aisance, de 0 à 1."""
    r = float(profile.get("lossReaction", 2)) / 3
    o = OBJECTIVE_TOLERANCE.get(str(profile.get("objective")), 0.5)
    c = (float(profile.get("comfort", 3)) - 1) / 4
    return 0.5 * _clamp(r) + 0.3 * o + 0.2 * _clamp(c)


def risk_position(profile: dict, adjustment: int = 0) -> float:
    """S, de 0 (très prudent) à 1 (très audacieux): moyenne des deux axes, la capacité limitant la tolérance."""
    c = capacity(profile)
    s = min((c + tolerance(profile)) / 2, c + CAPACITY_MARGIN)
    return _clamp(s + ADJUSTMENT_STEP * max(-2, min(2, adjustment)))


def _interpolate(s: float, anchors: list[tuple[float, float]], log: bool = False) -> float:
    for (s0, v0), (s1, v1) in zip(anchors, anchors[1:]):
        if s <= s1:
            t = (_clamp(s) - s0) / (s1 - s0)
            return v0 * (v1 / v0) ** t if log else v0 + (v1 - v0) * t
    return anchors[-1][1]


def risk_aversion(s: float) -> float:
    """Coefficient A donné à l'optimiseur: 25 très prudent … 1 très audacieux."""
    return round(_interpolate(s, AVERSION_ANCHORS, log=True), 2)


def risk_label(s: float) -> str:
    return RISK_LABELS[min(4, int(_clamp(s) / 0.2))]


def risk_score(profile: dict) -> int:
    """Score 5–95 du frontend (riskScore()), tiré de S."""
    return front_score(risk_position(profile))


def front_score(s: float) -> int:
    return math.floor(5 + 90 * s + 0.5)  # arrondi de Math.round, pas celui de round() (au pair)


def coherence_facts(profile: dict, prefs: dict) -> list[str]:
    score, classes = risk_score(profile), prefs.get("classes") or {}
    crypto, actions = classes.get("crypto", 0), classes.get("actions", 0)
    out = []
    if score < 40 and crypto >= 1:
        out.append("Tu cherches plutôt de la stabilité, mais tu demandes plus de crypto-actifs. Les deux se marient mal : "
                   "la crypto peut perdre la moitié de sa valeur en quelques mois.")
    if score < 40 and actions == 2:
        out.append("Imposer beaucoup d’actions avec un profil prudent peut te faire vivre des baisses difficiles à supporter.")
    if score > 65 and actions <= -1:
        out.append("Ton profil est dynamique, mais tu limites les actions : le rendement attendu sera plus faible que ce "
                   "que ton horizon permet.")
    kept = [k for k in CLASSES if classes.get(k, 0) != -2]
    if len(kept) == 1:
        out.append(f"Tu n’as gardé qu’un seul type de placement ({CLASS_LABELS[kept[0]].lower()}) : ton portefeuille sera "
                   "très peu diversifié.")
    return out


def computed_profile(profile: dict) -> dict:
    """Le profil de risque calculé, tel que Pépite le reçoit."""
    s = risk_position(profile)
    return {"capacite": round(capacity(profile), 2), "tolerance": round(tolerance(profile), 2),
            "libelle": risk_label(s), "aversion_au_risque": risk_aversion(s)}


def assess(profile: dict, review: PepiteReview | PepiteCheck, adjustment: int = 0) -> PepiteCheck:
    """Le profil de risque vient du code; Pépite apporte le texte, la cohérence et, au plus, ±2 crans d'ajustement."""
    s = risk_position(profile, adjustment)
    return PepiteCheck(
        **review.model_dump(include={"summary", "key_points", "flags", "coherent", "issues"}),
        risk_score=max(1, min(10, round(1 + 9 * s))), risk_label=risk_label(s), risk_position=round(s, 3),
        risk_aversion=risk_aversion(s), suggested_max_volatility=round(_interpolate(s, VOL_ANCHORS), 3),
        suggested_max_position_weight=round(_interpolate(s, STOCK_ANCHORS), 3),
    )


def fallback_check(profile: dict, facts: list[str]) -> PepiteCheck:
    """Si Pépite ne répond pas: cohérence tirée des faits calculés."""
    return assess(profile, PepiteReview(summary="J’ai relu tes réponses.", coherent=not facts,
                                        issues=[CoherenceIssue(title="À vérifier", detail=f) for f in facts]))


def slot_position(check: PepiteCheck, slot: str) -> Optional[float]:
    """La position S que suit un gestionnaire; None pour « Tes préférences » (profil incohérent), qui ignore le profil."""
    if not check.coherent:
        return None if slot == "conviction" else check.risk_position
    return _clamp(check.risk_position + SLOT_SHIFT[slot])


def slot_volatility(check: PepiteCheck, slot: str) -> Optional[float]:
    s = slot_position(check, slot)
    return None if s is None else round(_interpolate(s, VOL_ANCHORS), 3)


# --------------------------------------------------------------------------- #
# Profils de contraintes: Pépite propose, le code valide
# --------------------------------------------------------------------------- #
def _limits(vol: float, weight: float) -> list[Constraint]:
    """Limites du profil: volatilité, et poids par titre détenu en direct (un FNB n'est plafonné qu'à 40 %)."""
    return [Constraint(type=T.MAX_VOLATILITY, value=round(vol, 3), hard=True, note="Limite du profil"),
            Constraint(type=T.MAX_STOCK_WEIGHT, value=round(min(weight, LINE_CAP), 3), hard=True, note="Limite du profil"),
            Constraint(type=T.MAX_POSITION_WEIGHT, value=LINE_CAP, hard=True, note="Limite de sécurité")]


def follow_profile(constraints: list[Constraint], floor: float, risk_label: str,
                   allowed: dict[str, list[str]]) -> list[Constraint]:
    """Impose la répartition du profil: la part d'obligations et, pour un profil prudent, pas de crypto.
    Ces règles remplacent les poids que les préférences visaient sur les mêmes classes; une exclusion des
    obligations par le client l'emporte sur le plancher."""
    present = {v.lower(): v for v in allowed["asset_class"]}
    bonds = next((present[t.lower()] for t in BOND_TARGETS if t.lower() in present), None)
    cryptos = [present[t.lower()] for t in CRYPTO_TARGETS if t.lower() in present] if risk_label in NO_CRYPTO else []
    excluded = {(c.target or "").lower() for c in constraints if c.type is T.EXCLUDE_ASSET_CLASS}
    if bonds and (floor <= 0 or bonds.lower() in excluded):
        bonds = None
    managed = {t.lower() for t in [bonds, *cryptos] if t}
    out = [c for c in constraints if not (c.type in (T.MIN_ASSET_CLASS_WEIGHT, T.MAX_ASSET_CLASS_WEIGHT)
                                          and (c.target or "").lower() in managed)]
    out += [Constraint(type=T.EXCLUDE_ASSET_CLASS, target=t, hard=True, note=PROFILE_NOTE)
            for t in cryptos if t.lower() not in excluded]
    if bonds:
        out.append(Constraint(type=T.MIN_ASSET_CLASS_WEIGHT, target=bonds, value=round(floor, 2), hard=True, note=PROFILE_NOTE))
    if detect_conflicts(out):  # la répartition du profil passe avant les autres poids minimaux
        out = [c for c in out if not c.type.value.startswith("min_") or c.note == PROFILE_NOTE]
    return out


def promote_preferences(constraints: list[Constraint]) -> list[Constraint]:
    """« Moins » et « Plus » deviennent des contraintes dures, une à une, tant qu'elles ne créent pas de conflit:
    dans les portefeuilles qui suivent les préférences, elles doivent changer les poids, pas seulement être vérifiées."""
    out = list(constraints)
    for i, c in enumerate(out):
        if not c.hard:
            candidate = out[:i] + [c.model_copy(update={"hard": True})] + out[i + 1:]
            if not detect_conflicts(candidate):
                out = candidate
    return out


def fallback_plan(check: PepiteCheck, prefs: list[Constraint]) -> dict[str, tuple[str, list[Constraint]]]:
    """Profils écrits par le code si Pépite échoue ou si l'un des siens est inutilisable."""
    vol, weight = check.suggested_max_volatility, check.suggested_max_position_weight
    exclusions = [c for c in prefs if c.type.value.startswith("exclude_")]
    if check.coherent:
        return {
            "prudent": ("Un cran plus prudent que tes réponses.", prefs + _limits(slot_volatility(check, "prudent"), weight)),
            "equilibre": ("Fidèle à tes réponses.", prefs + _limits(vol, weight)),
            "conviction": ("Un cran plus audacieux que tes réponses.",
                           prefs + _limits(slot_volatility(check, "conviction"), weight)),
        }
    return {
        "prudent": ("Seulement les limites de ton profil.", exclusions + _limits(vol, weight)),
        "equilibre": ("Tout ce que tu as demandé.", prefs + _limits(vol, weight)),
        "conviction": ("Seulement tes préférences.", prefs + [Constraint(type=T.MAX_POSITION_WEIGHT, value=LINE_CAP)]),
    }


def objective_for(slot: str, check: PepiteCheck) -> tuple[str, Optional[float]]:
    """Moyenne-variance avec le A du gestionnaire; « Tes préférences » (profil incohérent) vise le meilleur
    rendement pour le risque, sans aversion tirée du profil."""
    s = slot_position(check, slot)
    return ("max_sharpe", None) if s is None else ("mean_variance", risk_aversion(s))


def guidance_for(aversion: Optional[float]) -> str:
    if aversion is None:
        return GUIDANCE["max_sharpe"]
    style = GUIDANCE["min_volatility" if aversion >= 7 else "max_sharpe" if aversion >= 3.5 else "max_return"]
    return (f"Aversion au risque A = {aversion:g} (1 très audacieux, 25 très prudent): l'optimiseur maximise le "
            f"rendement moins A/2 fois la variance. {style}")


def bond_floors(check: PepiteCheck) -> dict[str, float]:
    """Incohérent: seul « Ton profil » suit la répartition du profil. Cohérent: les 3 variantes, décalées de ±10 points."""
    base = BOND_FLOOR.get(check.risk_label, 0.0)
    if not check.coherent:
        return {"prudent": base}
    return {s: min(0.9, max(0.0, base + BOND_SHIFT[s])) if base else 0.0 for s in SLOTS}


def validate_profile(constraints: list[Constraint], exclusions: list[Constraint],
                     allowed: dict[str, list[str]]) -> Optional[list[Constraint]]:
    """Catalogue, exclusions du client et limite de 40 % garanties par le code. None si le profil reste contradictoire."""
    valid, errors = validate_all(constraints, allowed)
    if errors:
        logger.info("Contraintes de Pépite écartées: %s", errors)
    # Un plafond par titre sous 40 % vise les titres détenus en direct: un FNB d'obligations doit pouvoir peser 40 %.
    caps = [c.value for c in valid if c.type in (T.MAX_POSITION_WEIGHT, T.MAX_STOCK_WEIGHT) and c.hard and c.value]
    valid = [c for c in valid if c.type not in (T.MAX_POSITION_WEIGHT, T.MAX_STOCK_WEIGHT)]
    valid.append(Constraint(type=T.MAX_POSITION_WEIGHT, value=LINE_CAP, hard=True, note="Limite de sécurité"))
    if caps and min(caps) < LINE_CAP:
        valid.append(Constraint(type=T.MAX_STOCK_WEIGHT, value=min(caps), hard=True, note="Limite du profil"))
    valid = _dedupe(valid + exclusions)
    if detect_conflicts(valid):  # on retire d'abord les poids minimaux, cause habituelle des conflits
        valid = [c for c in valid if not c.type.value.startswith("min_")]
    return None if detect_conflicts(valid) else valid


def ensure_feasible(market: Market, constraints: list[Constraint]) -> tuple[list[Constraint], Optional[str]]:
    """Relève le plafond de volatilité quand l'univers ne permet pas de descendre aussi bas: sans ça, le gestionnaire
    et son repli échouent tous les deux (possible pour un profil très prudent)."""
    hard = [c for c in constraints if c.hard]
    caps = [c.value for c in hard if c.type is T.MAX_VOLATILITY and c.value]
    if not caps:
        return constraints, None
    eligible = market.assets[~excluded_mask(market, hard)]
    picks = eligible.sort_values("ann_vol").index[:30].tolist()
    for c in hard:  # les poids minimaux exigent des titres de leur groupe
        column = DIMENSION_COLUMN.get(c.type.value.removeprefix("min_").removesuffix("_weight"))
        if c.type.value.startswith("min_") and c.target and column:
            group = eligible[eligible[column].str.lower() == c.target.lower()]
            picks += group.sort_values("sharpe", ascending=False).index[:3].tolist()
    picks = list(dict.fromkeys(picks))[: get_settings().max_assets_per_portfolio]
    others = [c for c in constraints if not (c.hard and c.type is T.MAX_VOLATILITY)]
    lowest = optimize(market, picks, "min_volatility", others)
    if not lowest.ok or not lowest.metrics or lowest.metrics.volatility <= min(caps):
        return constraints, None
    cap = math.ceil((lowest.metrics.volatility + 0.003) * 100) / 100
    note = "L’univers de placements ne permet pas un risque aussi bas que demandé : j’ai visé le plus bas possible."
    return others + [Constraint(type=T.MAX_VOLATILITY, value=cap, hard=True, note="Plafond relevé au plus bas possible")], note


def build_profiles(plan: Optional[ConstraintPlan], check: PepiteCheck, prefs: list[Constraint],
                   allowed: dict[str, list[str]]) -> tuple[dict[str, tuple[str, list[Constraint]]], int]:
    """Retourne les 3 profils par slot et le nombre de profils remplacés par ceux du code."""
    fallback = fallback_plan(check, prefs)
    floors = bond_floors(check)
    exclusions = [c for c in prefs if c.type.value.startswith("exclude_")]
    proposed = {p.slot: p for p in (plan.profiles if plan else [])}
    out, replaced = {}, 0
    for slot in SLOTS:
        p = proposed.get(slot)
        constraints = validate_profile(p.constraints, exclusions, allowed) if p else None
        rationale = p.rationale if p else ""
        if constraints is None:
            replaced += 1
            rationale, raw = fallback[slot]
            constraints = validate_profile(raw, exclusions, allowed) or _limits(check.suggested_max_volatility, LINE_CAP)
        # Le plafond par titre du profil, si Pépite l'a oublié (sauf « Tes préférences », qui ignore le profil).
        if (check.coherent or slot != "conviction") and not any(c.type is T.MAX_STOCK_WEIGHT for c in constraints):
            cap = min(check.suggested_max_position_weight, LINE_CAP)
            constraints = constraints + [Constraint(type=T.MAX_STOCK_WEIGHT, value=cap, hard=True, note="Limite du profil")]
        # « Ton profil » (incohérent) ignore les préférences; partout ailleurs, elles comptent pour de vrai.
        if check.coherent or slot != "prudent":
            constraints = promote_preferences(constraints)
        if slot in floors:
            constraints = follow_profile(constraints, floors[slot], check.risk_label, allowed)
        # Le plafond de volatilité vient du code, à la position du gestionnaire (filet de sécurité sous A).
        constraints = [c for c in constraints if c.type is not T.MAX_VOLATILITY]
        if (vol := slot_volatility(check, slot)) is not None:
            constraints.append(Constraint(type=T.MAX_VOLATILITY, value=vol, hard=True, note="Limite du profil"))
        out[slot] = (rationale, constraints)
    return out, replaced


# --------------------------------------------------------------------------- #
# Portefeuilles: mélange 80/20 et gagnant
# --------------------------------------------------------------------------- #
def blend(market: Market, slot: str, core: Optional[Portfolio], satellite: Optional[Portfolio]) -> Optional[Portfolio]:
    """Cœur-satellite: 80 % du capital suit `core`, 20 % suit `satellite`. Poids et indicateurs recalculés par le code."""
    name, description = TRIO[slot]
    if core is None or satellite is None:
        base = core or satellite
        return base.model_copy(update={"id": slot, "mandate": name, "mandate_description": description}) if base else None
    weights: dict[str, float] = {}
    for p, share in ((core, BLEND), (satellite, 1 - BLEND)):
        for pos in p.positions:
            weights[pos.symbol] = weights.get(pos.symbol, 0.0) + share * pos.weight
    positions = []
    for symbol, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        a = market.assets.loc[symbol]
        positions.append(Position(symbol=symbol, name=str(a["name"]), weight=round(w, 4), sector=str(a["sector"]),
                                  country=str(a["country"]), asset_class=str(a["asset_class"])))
    return Portfolio(
        id=slot, mandate=name, mandate_description=description, positions=positions,
        metrics=market.portfolio_metrics(weights),
        summary=f"{BLEND:.0%} du portefeuille « {core.mandate} » et {1 - BLEND:.0%} du portefeuille « {satellite.mandate} ».".replace("%", " %"),
        tradeoffs=core.summary,
    )


def pick_winner(portfolios: list[Portfolio], verdicts: dict[str, JudgeVerdict], choice: Optional[str]) -> Portfolio:
    """Le choix du juge final, s'il est conforme ou si aucun ne l'est; sinon le conforme le mieux noté."""
    def rank(p: Portfolio) -> tuple:
        v = verdicts.get(p.id)
        return (bool(v and v.compliant), v.fit_score if v else 0, p.metrics.sharpe if p.metrics else 0)

    best = max(portfolios, key=rank)
    chosen = next((p for p in portfolios if p.id == choice), None)
    return chosen if chosen and rank(chosen)[0] >= rank(best)[0] else best


# --------------------------------------------------------------------------- #
# Sortie: Portfolio du frontend
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


def to_portfolio(p: Portfolio, verdict: Optional[JudgeVerdict], market: Market, risk_report: Optional[dict],
                 position: float, skipped: list[str], extra: list[str], name: str, tagline: str) -> dict:
    holdings, allocation, fees = [], {c: 0.0 for c in CLASSES}, 0.0
    for pos in p.positions:
        row = market.assets.loc[pos.symbol] if pos.symbol in market.assets.index else pos.model_dump()
        cls = front_class(row)
        holdings.append({"ticker": pos.symbol, "name": pos.name, "assetClass": cls, "weight": pos.weight})
        allocation[cls] += pos.weight
        fees += pos.weight * FEES.get(str(row.get("instrument_type", "")), 0.0)

    m = p.metrics
    mu, sigma = (m.expected_return, m.volatility) if m else (0.0, 0.0)
    warnings = [f"{w['title']}. {w['detail']}" for w in (risk_report or {}).get("warnings", [])
                if w.get("portfolio_id") == p.id and w.get("severity") in ("medium", "high")]
    agent_notes = [t for t in (p.summary, p.tradeoffs, verdict.comment if verdict else None) if t] + extra
    if skipped:
        agent_notes.append(f"Pas encore pris en compte par les agents : {', '.join(skipped)}.")
    if verdict and not verdict.compliant:
        warnings.insert(0, "Ce portefeuille ne respecte pas toutes tes limites. Lis les détails avant de le choisir.")
    elif verdict:
        agent_notes.append("Le juge confirme que ce portefeuille respecte tes limites.")
    return {
        "id": p.id,
        "name": name,
        "tagline": tagline,
        "riskScore": front_score(position),
        "holdings": holdings,
        "allocation": {k: round(v, 4) for k, v in allocation.items()},
        # Mêmes formules que metricsOf() dans frontend/src/lib/engine.ts, sur les chiffres de l'optimiseur.
        "metrics": {
            "expectedReturn": mu,
            "volatility": sigma,
            "worstYear": mu - 2.33 * sigma,
            "fees": round(fees, 5),
            "sharpe": m.sharpe if m else 0.0,
            "maxDrawdown": m.max_drawdown if m else 0.0,
            "var95": -(mu - 1.645 * sigma),
            "es95": -(mu - 2.063 * sigma),
        },
        "warnings": warnings,
        "agentNotes": agent_notes,
    }


# --------------------------------------------------------------------------- #
# Événements: bus des agents -> PipelineEvent
# --------------------------------------------------------------------------- #
TOOL_TEXT = {
    "describe_universe": "tour d’horizon des placements",
    "screen_assets": "recherche de placements",
    "optimize_portfolio": "calcul des poids",
}


def status(agent: str, state: str, message: str) -> dict:
    return {"type": "agent_status", "agent": agent, "status": state, "message": message}


def pepite(text: str) -> dict:
    return {"type": "pepite", "text": text}


class Translator:
    """Les statuts des agents deviennent des cartes: gestionnaire-<slot>, juge-<slot>, juge-final, risques.
    Les événements « front » sont émis tels quels par l'orchestration (carte Pépite, portefeuilles…)."""

    def __init__(self) -> None:
        self.slots: dict[str, str] = {}  # nom de mandat -> slot, rempli quand les profils sont prêts

    def translate(self, e: dict) -> Iterable[dict]:
        kind, agent, state = e.get("type"), e.get("agent") or "", e.get("state")
        if kind == "front":
            yield e["event"]
        elif kind == "heartbeat":
            yield {"type": "heartbeat"}
        elif agent == "Juge final":
            if state == "start":
                yield status("juge-final", "running", "Comparaison des 3 portefeuilles…")
        elif agent == "CRO":
            if state == "start":
                yield status("risques", "running", "Recherche des incohérences avec ton profil…")
        elif agent.startswith("PM ") and (slot := self.slots.get(agent.removeprefix("PM "))):
            card = f"gestionnaire-{slot}"
            if kind == "tool" and e.get("name") in TOOL_TEXT:
                yield status(card, "running", f"{TOOL_TEXT[e['name']].capitalize()}…")
            elif state == "start":
                yield status(card, "running", "Construction du portefeuille…")
            elif state == "warning":
                yield status(card, "running", "Sélection de secours en cours…")
            elif state == "done":
                yield status(card, "done", "Portefeuille prêt.")
        elif agent.startswith("Juge ") and (slot := self.slots.get(agent.removeprefix("Juge "))):
            if state == "start":
                yield status(f"juge-{slot}", "running", "Vérification de tes limites…")
            elif state in ("done", "warning"):
                yield status(f"juge-{slot}", "done", "Évaluation terminée.")


def front(bus: EventBus, event: dict) -> None:
    bus.emit("front", event=event)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _questionnaire(payload: dict) -> tuple[dict, dict]:
    """Le JSON du questionnaire, sans les ajouts prévus (jamais envoyés aux agents)."""
    return payload.get("profile") or {}, payload.get("constraints") or {}


async def _check(bus: EventBus, profile: dict, prefs: dict) -> PepiteCheck:
    facts = coherence_facts(profile, prefs)
    try:
        review = await run_check(bus, {"profile": profile, "constraints": prefs}, computed_profile(profile), facts)
        return assess(profile, review)
    except AgentError:
        logger.exception("Vérification de Pépite en échec, repli sur les règles du code")
        return fallback_check(profile, facts)


async def check_questionnaire(payload: dict, bus: EventBus) -> None:
    profile, prefs = _questionnaire(payload)
    market = await asyncio.to_thread(get_market)
    to_form(profile, prefs, market)  # valide le profil avant d'appeler le modèle
    check = await _check(bus, profile, prefs)
    front(bus, {"type": "check", "check": check.model_dump(mode="json")})
    front(bus, {"type": "done"})


async def _judge(bus: EventBus, market: Market, investor: InvestorProfile, p: Portfolio) -> JudgeVerdict:
    try:
        return await run_judge(bus, market, investor, p, investor.constraints)
    except Exception as exc:  # noqa: BLE001  même repli que orchestrator._judge_portfolios
        logger.exception("Juge %s en échec", p.id)
        checks = evaluate(market, {x.symbol: x.weight for x in p.positions}, investor.constraints)
        hard = sum(1 for c in checks if c.constraint.hard and not c.passed)
        soft = sum(1 for c in checks if not c.constraint.hard and not c.passed)
        return JudgeVerdict(portfolio_id=p.id, compliant=hard == 0, hard_violations=hard, soft_violations=soft,
                            checks=checks, fit_score=0, comment=f"Avis indisponible ({type(exc).__name__}).")


async def build_portfolios(payload: dict, bus: EventBus, translator: Translator) -> None:
    profile, prefs = _questionnaire(payload)
    market = await asyncio.to_thread(get_market)
    form, skipped = to_form(profile, prefs, market)
    try:  # le profil de risque est recalculé: seuls le texte et la cohérence de Pépite sont repris
        check = assess(profile, PepiteCheck.model_validate(payload.get("check")))
    except ValidationError:
        check = await _check(bus, profile, prefs)
    coherent = check.coherent
    adjustment = str(payload.get("adjustment") or "").strip()[:MAX_ADJUSTMENT] if coherent else ""

    # Pépite écrit les 3 profils de contraintes
    front(bus, pepite("C’est parti! J’écris les consignes de tes trois gestionnaires."))
    front(bus, status("pepite", "running", "J’écris les 3 profils de contraintes…"))
    allowed = market.allowed_values()
    direct = [v for v in allowed["asset_class"] if v in DIRECT_CLASSES]
    try:
        plan = await run_plan(bus, {"profile": profile, "constraints": prefs}, check, adjustment, allowed, direct)
    except AgentError:
        logger.exception("Plan de Pépite en échec, repli sur les profils du code")
        plan = None
    if plan and adjustment and plan.risk_adjustment:  # « je veux dormir tranquille »: au plus une demi-catégorie
        check = assess(profile, check, plan.risk_adjustment)
        if plan.risk_adjustment_reason:
            front(bus, pepite(plan.risk_adjustment_reason))
    profiles, replaced = build_profiles(plan, check, list(form.constraints), allowed)
    if replaced:
        logger.info("%d profil(s) de Pépite remplacé(s) par ceux du code", replaced)
    notes: dict[str, list[str]] = {s: [] for s in SLOTS}
    for slot in SLOTS:
        constraints, note = await asyncio.to_thread(ensure_feasible, market, profiles[slot][1])
        profiles[slot] = (profiles[slot][0], constraints)
        if note:
            notes[slot].append(note)
    hard = [c for c in profiles["equilibre"][1] if c.hard]
    before, after = len(market.assets), int((~excluded_mask(market, hard)).sum())
    front(bus, {"type": "universe", "before": before, "after": after})
    front(bus, status("pepite", "done", "3 profils de contraintes envoyés aux gestionnaires."))

    # 3 gestionnaires en parallèle, un profil chacun
    names = VARIANT_NAMES if coherent else BASE_NAMES
    translator.slots = {names[s]: s for s in SLOTS}
    investors = {s: InvestorProfile(form=form, assessment=check, constraints=profiles[s][1]) for s in SLOTS}

    async def manage(slot: str) -> Portfolio:
        objective, aversion = objective_for(slot, check)
        mandate = Mandate(id=slot, name=names[slot], objective=objective, description=profiles[slot][0],
                          guidance=guidance_for(aversion), vol_cap_factor=None, risk_aversion=aversion)
        try:
            return await run_portfolio_manager(bus, market, mandate, investors[slot], investors[slot].constraints)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Gestionnaire %s en échec", slot)
            return Portfolio(id=slot, mandate=mandate.name, mandate_description=mandate.description,
                             status="failed", failure_reason=type(exc).__name__)

    front(bus, pepite("Mes trois gestionnaires construisent leur portefeuille en parallèle."))
    built = [p for p in await asyncio.gather(*(manage(s) for s in SLOTS)) if p.status == "ok"]
    if not built:
        front(bus, {"type": "error", "message": "Aucun portefeuille n’a pu être construit. Réessaie dans un instant."})
        return
    verdicts = dict(zip([p.id for p in built], await asyncio.gather(*(_judge(bus, market, investors[p.id], p) for p in built))))
    for slot in SLOTS:
        v = verdicts.get(slot)
        text = ("Pas de portefeuille à vérifier." if v is None else "Toutes tes limites sont respectées." if v.compliant
                else f"{v.hard_violations} limite(s) non respectée(s).")
        front(bus, status(f"juge-{slot}", "done", text))

    # Cohérent: un gagnant. Incohérent: tes contraintes + deux mélanges 80/20.
    if coherent:
        choice, justification = None, ""
        if len(built) > 1:
            try:
                pick = await run_final_judge(bus, investors["equilibre"], built, verdicts)
                choice, justification = pick.winner, pick.justification
            except AgentError:
                logger.exception("Juge final en échec, choix par le code")
        winner = pick_winner(built, verdicts, choice)
        if winner.id != choice:
            justification = f"La {winner.mandate.lower()} respecte le mieux tes limites, avec la meilleure note du juge."
        front(bus, status("juge-final", "done", f"La {winner.mandate.lower()} l’emporte."))
        presented = [(winner, verdicts.get(winner.id), WINNER_NAME, justification)]
    else:
        by = {p.id: p for p in built}
        presented = []
        for slot, p in (("prudent", blend(market, "prudent", by.get("prudent"), by.get("conviction"))),
                        ("equilibre", by.get("equilibre")),
                        ("conviction", blend(market, "conviction", by.get("conviction"), by.get("prudent")))):
            if p is not None:
                p = p.model_copy(update={"mandate": TRIO[slot][0]})
                # Les juges ont vérifié les bases; seul « Tes contraintes » est présenté tel quel.
                presented.append((p, verdicts.get(slot) if slot == "equilibre" else None, *TRIO[slot]))
        front(bus, status("pepite", "done", "Mélanges 80/20 prêts : profil d’abord, préférences d’abord."))

    # Responsable des risques, puis les portefeuilles
    report = None
    try:
        rr = await run_cro(bus, investors["equilibre"], [p for p, *_ in presented],
                           {p.id: v for p, v, *_ in presented if v})
        report = rr.model_dump(mode="json")
    except AgentError:
        logger.exception("CRO en échec")
    n = sum(1 for w in (report or {}).get("warnings", []) if w.get("severity") in ("medium", "high"))
    # Les incohérences du profil, Pépite les a déjà montrées avant l'envoi: on ne garde que les mises en garde
    # sur les portefeuilles.
    front(bus, status("risques", "done", f"{n} mise(s) en garde à lire." if n else "Rien de particulier à signaler."))
    front(bus, {"type": "portfolios", "portfolios": {
        p.id: to_portfolio(p, v, market, report, check.risk_position, skipped, notes[p.id], name, tagline)
        for p, v, name, tagline in presented
    }})
    front(bus, pepite("Voilà! Ton portefeuille t’attend." if coherent
                      else "Voilà! Trois propositions t’attendent. C’est toi qui choisis."))
    front(bus, {"type": "done"})


# --------------------------------------------------------------------------- #
# Points d'entrée (main.py)
# --------------------------------------------------------------------------- #
async def _stream(work: Callable[[EventBus], Awaitable[None]], translator: Translator) -> AsyncIterator[dict]:
    bus = EventBus()

    async def worker() -> None:
        try:
            await work(bus)
        except (ValidationError, TypeError, ValueError) as exc:
            logger.warning("Profil MonPort invalide: %s", exc)
            front(bus, {"type": "error", "message": "Ton profil est incomplet. Reprends le questionnaire."})
        except Exception:  # noqa: BLE001
            logger.exception("Erreur inattendue (MonPort)")
            front(bus, {"type": "error", "message": "Mes agents ont eu un pépin. Réessaie dans un instant."})
        finally:
            bus.close()

    task = asyncio.create_task(worker())
    async for event in bus.stream(task):
        for out in translator.translate(event):
            yield out


def stream_check(payload: dict) -> AsyncIterator[dict]:
    return _stream(lambda bus: check_questionnaire(payload, bus), Translator())


def stream_monport(payload: dict) -> AsyncIterator[dict]:
    translator = Translator()
    return _stream(lambda bus: build_portfolios(payload, bus, translator), translator)
