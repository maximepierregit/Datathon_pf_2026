"""Contrat avec le frontend (frontend/src/types.ts): entrées, traduction des préférences, sorties.

Le frontend envoie le profil et les préférences sur l'échelle Exclure (−2) … Imposer (+2). Ce module les
traduit en contraintes du catalogue, différentes pour chaque portefeuille:

- Prudent: le profil d'abord. Les préférences pour plus de risque sont mises de côté.
- Équilibré: le juste milieu.
- Conviction: les préférences d'abord, dans les limites de sécurité.

Les exclusions (−2) s'appliquent aux trois. Les limites de sécurité sont dures partout: aucune ligne au-delà
de 40 % et jamais un seul placement.
"""

from __future__ import annotations

import math
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .classify import ASSET_CLASSES, FACTORS, REGIONS, THEMES
from .config import get_settings
from .constraints import SPECS, describe, detect_conflicts
from .data import Market
from .mandates import Mandate
from .optimizer import optimize
from .schemas import Constraint, ConstraintType as T, InvestorForm, Portfolio as InternalPortfolio
from .selection import default_selection

LINE_CAP = 0.40
MIN_LINES = 3
RISKY = {"actions", "immobilier", "or", "crypto"}

CLASS_LABELS = {
    "actions": "Actions", "obligations": "Obligations", "immobilier": "Immobilier coté",
    "or": "Or et matières premières", "crypto": "Crypto-actifs", "liquidites": "Liquidités",
}
REGION_LABELS = {"canada": "Canada", "usa": "États-Unis", "europe": "Europe", "asie": "Asie-Pacifique",
                 "emergents": "Marchés émergents"}
THEME_LABELS = {
    "tech": "Technologie", "ia": "Intelligence artificielle", "sante": "Santé", "energie-propre": "Énergie propre",
    "fossiles": "Énergies fossiles", "finance": "Banques et assurances", "immobilier": "Immobilier",
    "consommation": "Consommation", "industrie": "Industrie et infrastructures", "armement": "Armement",
    "alcool-tabac": "Alcool et tabac",
}
FACTOR_LABELS = {"taille": "Petites capitalisations", "qualite": "Qualité", "momentum": "Momentum", "value": "Value"}


# --------------------------------------------------------------------------- #
# Entrées (miroir de types.ts)
# --------------------------------------------------------------------------- #
class FrontendProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    age: int = Field(ge=18, le=110)
    amount: float = Field(gt=0)
    objective: Literal["securiser", "fructifier", "viser-haut"]
    horizon: int = Field(ge=0, le=60)
    lossReaction: int = Field(ge=0, le=3)
    comfort: int = Field(ge=1, le=5)


def _levels(raw: dict, allowed: list[str]) -> dict[str, int]:
    out = {}
    for k, v in (raw or {}).items():
        if k in allowed and int(v) in (-2, -1, 1, 2):
            out[k] = int(v)
    return out


class FrontendConstraints(BaseModel):
    model_config = ConfigDict(extra="ignore")
    vehicles: Literal["fnb", "tous"] = "tous"
    classes: dict[str, int] = Field(default_factory=dict)
    regions: dict[str, int] = Field(default_factory=dict)
    themes: dict[str, int] = Field(default_factory=dict)
    factors: dict[str, int] = Field(default_factory=dict)

    @field_validator("classes")
    @classmethod
    def _c(cls, v: dict) -> dict:
        return _levels(v, ASSET_CLASSES)

    @field_validator("regions")
    @classmethod
    def _r(cls, v: dict) -> dict:
        return _levels(v, REGIONS)

    @field_validator("themes")
    @classmethod
    def _t(cls, v: dict) -> dict:
        return _levels(v, THEMES)

    @field_validator("factors")
    @classmethod
    def _f(cls, v: dict) -> dict:
        return _levels(v, FACTORS)


# --------------------------------------------------------------------------- #
# Profil
# --------------------------------------------------------------------------- #
def risk_score(p: FrontendProfile) -> int:
    """Copie exacte de `riskScore` (frontend/src/lib/engine.ts)."""
    age = 20 if p.age < 30 else 12 if p.age < 45 else 4 if p.age < 60 else -10
    horizon = min(p.horizon, 25)
    objective = {"securiser": 0, "fructifier": 15, "viser-haut": 30}[p.objective]
    raw = age + horizon + objective + p.lossReaction * 10
    return max(5, min(95, math.floor(raw + 0.5)))  # Math.round de JavaScript


def to_investor_form(p: FrontendProfile) -> InvestorForm:
    """Traduit le questionnaire du frontend en formulaire pour l'agent Profil."""
    return InvestorForm(
        age=p.age,
        investment_amount_cad=p.amount,
        horizon_years=max(1, p.horizon),
        risk_tolerance={0: 1, 1: 2, 2: 4, 3: 5}[p.lossReaction],
        loss_reaction=("vend_tout", "vend_une_partie", "attend", "investit_plus")[p.lossReaction],
        max_acceptable_loss_pct=None,  # le questionnaire ne le demande pas: ne pas l'inventer
        objective={"securiser": "preservation", "fructifier": "balanced", "viser-haut": "growth"}[p.objective],
        experience={1: "none", 2: "basic", 3: "intermediate", 4: "advanced", 5: "advanced"}[p.comfort],
        liquidity_needs="low" if p.horizon >= 5 else "medium" if p.horizon >= 2 else "high",
    )


# --------------------------------------------------------------------------- #
# Répartition stratégique (copie de `classWeights` sans préférences, engine.ts)
# --------------------------------------------------------------------------- #
def strategic_weights(mandate: Mandate, score: int) -> dict[str, float]:
    s = max(0, min(100, score + mandate.score_shift))
    eq = 0.15 + 0.7 * (s / 100)
    w = {"actions": eq, "immobilier": 0.04, "or": 0.03, "crypto": 0.0, "liquidites": max(0.03, 0.12 - s * 0.001)}
    w["obligations"] = max(0.0, 1 - sum(w.values()))
    return w


def _c(t: T, target: Optional[str], value: Optional[float], source: str, note: str, hard: bool = True) -> Constraint:
    return Constraint(type=t, target=target, value=None if value is None else round(value, 4),
                      hard=hard, source=source, note=note)  # type: ignore[arg-type]


def global_exclusions(fc: FrontendConstraints) -> list[Constraint]:
    """Exclusions communes aux trois portefeuilles (rôle de l'Éclaireur)."""
    out = []
    if fc.vehicles == "fnb":
        out.append(_c(T.EXCLUDE_INSTRUMENT_TYPE, "Stock", None, "preference", "FNB seulement : aucun titre individuel"))
    for k, lv in fc.classes.items():
        if lv == -2:
            out.append(_c(T.EXCLUDE_ASSET_CLASS, k, None, "preference", f"Exclure {CLASS_LABELS[k]}"))
    for k, lv in fc.regions.items():
        if lv == -2:
            out.append(_c(T.EXCLUDE_REGION, k, None, "preference", f"Exclure {REGION_LABELS[k]}"))
    for k, lv in fc.themes.items():
        if lv == -2:
            out.append(_c(T.EXCLUDE_THEME, k, None, "preference", f"Exclure {THEME_LABELS[k]}"))
    for k, lv in fc.factors.items():
        if lv == -2:
            out.append(_c(T.EXCLUDE_FACTOR, k, None, "preference", f"Exclure {FACTOR_LABELS[k]}"))
    return out


# Poids minimaux (Plus / Imposer) et maximaux (Moins) par mandat, pour régions, thèmes et facteurs.
_GROUP_LEVELS = {
    "prudent": {1: 0.03, 2: 0.05, -1: 0.05},
    "equilibre": {1: 0.08, 2: 0.15, -1: 0.05},
    "conviction": {1: 0.15, 2: 0.25, -1: 0.02},
}
_CLASS_PLUS = {"prudent": 0.05, "equilibre": 0.05, "conviction": 0.12}
_CLASS_IMPOSE = {"prudent": 0.10, "equilibre": 0.10, "conviction": 0.25}
CRYPTO_SAFETY_CAP = 0.20


def mandate_constraints(
    mandate: Mandate, score: int, fc: FrontendConstraints, market: Market, stock_cap: float = 0.10
) -> tuple[list[Constraint], list[str]]:
    """Contraintes d'un portefeuille et notes à afficher au client (préférences mises de côté, etc.)."""
    pid = mandate.id
    notes: list[str] = []
    out = [
        _c(T.MAX_POSITION_WEIGHT, None, LINE_CAP, "safety", "Aucune ligne au-delà de 40 %"),
        # Un FNB est déjà diversifié; une action seule ne l'est pas: elle suit le plafond du profil.
        _c(T.MAX_INSTRUMENT_LINE_WEIGHT, "Stock", stock_cap, "safety", "Plafond par titre individuel"),
        _c(T.MIN_POSITIONS, None, MIN_LINES, "safety", "Jamais tout sur un seul placement"),
        *global_exclusions(fc),
    ]
    if mandate.objective == "min_volatility":
        # Sans plancher, la volatilité minimale retient des placements qui ne rapportent presque rien.
        rf = get_settings().risk_free_rate
        out.append(_c(T.MIN_EXPECTED_RETURN, None, rf + 0.01, "mandate", "Rendement au moins supérieur aux liquidités"))
    available = set(market.groups("asset_class"))
    base = strategic_weights(mandate, score)

    # Classes d'actifs: bande autour de la répartition stratégique, déplacée par les préférences.
    for k in ASSET_CLASSES:
        lv = fc.classes.get(k, 0)
        if lv == -2 or k not in available:
            if lv > 0 and k not in available:
                notes.append(f"Aucun placement « {CLASS_LABELS[k]} » dans l’univers : ta préférence ne peut pas être suivie.")
            continue
        b = base[k]
        lo, hi = b * 0.8, min(1.0, b * 1.2 + 0.02)  # bande autour de la répartition du mandat
        source, note = "mandate", f"Répartition {mandate.name} : {CLASS_LABELS[k]}"
        if lv == -1:
            lo, hi = 0.0, b * (0.4 if pid == "conviction" else 0.6)
            source, note = "preference", f"Moins de {CLASS_LABELS[k]}"
        elif lv > 0 and pid == "prudent" and k in RISKY:
            notes.append(f"Ta préférence pour « {CLASS_LABELS[k]} » a été mise de côté : ton profil demande de la stabilité.")
        elif lv > 0:
            if k == "crypto":
                lo = {1: 0.10, 2: 0.20}[lv] if pid == "conviction" else {1: 0.03, 2: 0.05}[lv]
                hi = lo + (0.05 if pid == "conviction" else 0.02)
            else:
                lo = b + _CLASS_PLUS[pid] if lv == 1 else max(b, _CLASS_IMPOSE[pid])
                hi = max(hi, lo + (0.10 if lv == 1 else 0.15))
            source, note = "preference", f"{'Plus' if lv == 1 else 'Imposer'} : {CLASS_LABELS[k]}"
        if lo > 0.005:
            out.append(_c(T.MIN_ASSET_CLASS_WEIGHT, k, lo, source, note))
        if k == "crypto":  # plafond de sécurité, jamais assoupli
            out.append(_c(T.MAX_ASSET_CLASS_WEIGHT, k, min(hi, CRYPTO_SAFETY_CAP), "safety", "Crypto-actifs plafonnés"))
        else:
            out.append(_c(T.MAX_ASSET_CLASS_WEIGHT, k, min(1.0, hi), source, note))

    # Régions, thèmes, facteurs
    blocks = [
        ("region", fc.regions, REGION_LABELS, T.MIN_REGION_WEIGHT, T.MAX_REGION_WEIGHT),
        ("theme", fc.themes, THEME_LABELS, T.MIN_THEME_WEIGHT, T.MAX_THEME_WEIGHT),
        ("factor", fc.factors, FACTOR_LABELS, T.MIN_FACTOR_WEIGHT, T.MAX_FACTOR_WEIGHT),
    ]
    for dim, levels, labels, t_min, t_max in blocks:
        groups = set(market.groups(dim))
        for k, lv in levels.items():
            if lv == -2:
                continue
            if k not in groups:
                if lv > 0:
                    notes.append(f"Aucun placement « {labels[k]} » repéré dans l’univers : ta préférence ne peut pas être suivie.")
                continue
            v = _GROUP_LEVELS[pid][lv]
            if lv < 0:
                out.append(_c(t_max, k, v, "preference", f"Moins : {labels[k]}"))
            else:
                out.append(_c(t_min, k, v, "preference", f"{'Plus' if lv == 1 else 'Imposer'} : {labels[k]}"))
    return out, notes


# --------------------------------------------------------------------------- #
# Faisabilité: on assouplit dans l'ordre de priorité du mandat
# --------------------------------------------------------------------------- #
_RELAX_ORDER = {
    # sources assouplies en premier -> en dernier (safety et exclusions ne sont jamais assouplies)
    "prudent": ["preference", "mandate"],
    "equilibre": ["preference", "mandate"],
    "conviction": ["mandate", "preference"],
}



def make_feasible(
    market: Market, mandate: Mandate, constraints: list[Constraint], vol_cap: Optional[float]
) -> tuple[list[Constraint], list[str], Optional[float]]:
    """Rend les contraintes dures réalisables. Les contraintes assouplies deviennent des préférences
    (évaluées par le Juge) et une note explique ce qui a été mis de côté."""
    notes: list[str] = []
    cons = [c.model_copy() for c in constraints]

    def feasible(cap: Optional[float] = vol_cap) -> bool:
        if detect_conflicts(cons):
            return False
        sel = default_selection(market, cons, mandate.objective)
        return bool(sel) and optimize(market, sel, mandate.objective, cons, vol_cap=cap).ok

    if feasible():
        return cons, notes, vol_cap

    # Candidates à l'assouplissement: les moins importantes d'abord (facteurs, thèmes, régions, classes),
    # minimums avant plafonds, en suivant l'ordre des sources propre au mandat.
    dim_rank = {"factor": 0, "theme": 1, "region": 2, "asset_class": 3, None: 4}
    candidates = sorted(
        (c for c in cons if c.hard and c.source in _RELAX_ORDER[mandate.id] and SPECS[c.type].dimension in dim_rank
         and SPECS[c.type].kind == "fraction"),
        key=lambda c: (_RELAX_ORDER[mandate.id].index(c.source), SPECS[c.type].direction != "min",
                       dim_rank[SPECS[c.type].dimension]),
    )
    relaxed: list[Constraint] = []
    for c in candidates:
        c.hard = False
        relaxed.append(c)
        if feasible():
            break
    else:
        # Dernier recours: on retire aussi le plafond de volatilité du mandat (la sécurité reste dure).
        for c in relaxed:
            c.hard = True
        relaxed = []
        if feasible(None):
            return cons, notes + ["Le plafond de risque de ce portefeuille a été relâché pour respecter tes choix."], None
        return cons, notes, vol_cap  # le PM et le Juge signaleront l'écart

    # On rétablit chaque contrainte assouplie qui n'était pas nécessaire.
    for c in reversed(relaxed):
        c.hard = True
        if not feasible():
            c.hard = False
    return cons, notes + _relax_notes(cons), vol_cap


def _relax_notes(cons: list[Constraint]) -> list[str]:
    out = []
    for c in cons:
        if not c.hard and c.source == "preference":
            out.append(f"« {c.note} » n’a pas pu être appliqué entièrement : la combinaison de tes choix n’était pas réalisable.")
    return out


# --------------------------------------------------------------------------- #
# Sorties (miroir de types.ts)
# --------------------------------------------------------------------------- #
def to_frontend_portfolio(
    market: Market, mandate: Mandate, p: InternalPortfolio, score: int, warnings: list[str], notes: list[str]
) -> dict:
    m = p.metrics
    holdings = [
        {"ticker": x.symbol, "name": x.name, "assetClass": x.asset_class, "weight": round(x.weight, 4)}
        for x in p.positions
    ]
    allocation = {k: 0.0 for k in ASSET_CLASSES}
    for h in holdings:
        allocation[h["assetClass"]] = round(allocation.get(h["assetClass"], 0.0) + h["weight"], 4)
    mu, sigma = (m.expected_return, m.volatility) if m else (0.0, 0.0)
    metrics = {
        "expectedReturn": mu,
        "volatility": sigma,
        "worstYear": round(mu - 2.33 * sigma, 4),
        "fees": m.fees if m else 0.0,
        "sharpe": m.sharpe if m else 0.0,
        "maxDrawdown": m.max_drawdown if m else 0.0,
        "var95": round(-(mu - 1.645 * sigma), 4),
        "es95": round(-(mu - 2.063 * sigma), 4),
    }
    agent_notes = [x for x in [p.summary, *notes, p.tradeoffs] if x]
    return {
        "id": mandate.id,
        "name": mandate.name,
        "tagline": mandate.tagline,
        "riskScore": score,
        "holdings": holdings,
        "allocation": allocation,
        "metrics": metrics,
        "warnings": warnings,
        "agentNotes": agent_notes,
    }


def coherence_warnings(score: int, fc: FrontendConstraints) -> list[str]:
    """Copie de `coherenceWarnings` (engine.ts): alertes profil ↔ préférences."""
    w = []
    crypto, actions = fc.classes.get("crypto", 0), fc.classes.get("actions", 0)
    if score < 40 and crypto >= 1:
        w.append("Tu cherches plutôt de la stabilité, mais tu demandes plus de crypto-actifs. Les deux se marient mal : "
                 "la crypto peut perdre la moitié de sa valeur en quelques mois.")
    if score < 40 and actions == 2:
        w.append("Imposer beaucoup d’actions avec un profil prudent peut te faire vivre des baisses difficiles à supporter.")
    if score > 65 and actions <= -1:
        w.append("Ton profil est dynamique, mais tu limites les actions : le rendement attendu sera plus faible que ce "
                 "que ton horizon permet.")
    kept = [k for k in ASSET_CLASSES if fc.classes.get(k, 0) != -2]
    if len(kept) == 1:
        w.append(f"Tu n’as gardé qu’un seul type de placement ({CLASS_LABELS[kept[0]].lower()}) : ton portefeuille sera "
                 "très peu diversifié.")
    return w


def constraint_labels(cons: list[Constraint]) -> list[str]:
    return [describe(c) for c in cons]
