"""Règles déterministes de MonPort et traduction des événements pour le frontend.

L'orchestration est dans `workflow/` (Pépite pilote les agents). Ce module garde ce que le code garantit:
le profil de risque (capacité, tolérance, aversion A), la cohérence calculée, la traduction des préférences en
contraintes, les profils de contraintes validés, le mélange 80/20, le choix du gagnant et la forme des
portefeuilles que lit le frontend (`frontend/src/types.ts`).
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any, AsyncIterator, Awaitable, Callable, Iterable, Optional

from pydantic import ValidationError

from .runtime import get_runtime_settings
from .catalog import DIMENSION_COLUMN, SEP, SHARE_TYPES, detect_conflicts, excluded_mask, share_targets, validate_all
from .constraints import preference_exposure
from .market import Market
from .events import EventBus
from . import factors
from .allocator import optimize
from .tools import factor_fits
from .schemas import (
    CoherenceIssue,
    Constraint,
    ConstraintPlan,
    ConstraintType as T,
    InvestorForm,
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
# Thématiques: d'abord les tags vérifiés du Parquet (`theme`, data-prep/themes.csv), sinon les secteurs GICS.
# « alcool-tabac » prend le tag `vice`, plus large (il couvre aussi le cannabis et les jeux).
THEME_TAGS = {"tech": "tech", "ia": "ia", "energie-propre": "energie-propre", "armement": "armement",
              "alcool-tabac": "vice"}
THEME_SECTORS = {
    "sante": ["Health Care"],
    "fossiles": ["Energy"],
    "finance": ["Financials"],
    "immobilier": ["Real Estate"],
    "consommation": ["Consumer Staples", "Consumer Discretionary"],
    "industrie": ["Industrials"],
}
# Titres détenus en direct, écartés par « FNB seulement ». Par type d'instrument, pas par classe d'actifs: les FNB
# d'actions ont la classe « Equity », comme les actions.
DIRECT_TYPES = ("Stock", "Cryptocurrency")
FUND_TYPES = ("ETF",)  # écartés par « Titres individuels seulement »
# Classes proposées au client: jamais les liquidités; seulement actions et crypto pour des titres individuels.
SHOWN_CLASSES = {"titres": ["actions", "crypto"]}
BLOCK_LABELS = {"classes": "classe", "regions": "région", "themes": "thématique", "factors": "facteur"}
# Facteurs: identifiants du frontend (data/catalog.ts) -> facteurs du moteur (factors.py).
FACTOR_TARGETS = {"taille": "small_cap", "qualite": "quality", "momentum": "momentum", "value": "value",
                  "croissance": "growth"}
# Exposition visée par niveau, en écarts-types: Plus/Moins = légère inclinaison, Imposer/Exclure = nette (dure).
FACTOR_LEVELS = {2: 0.5, 1: 0.2, -1: -0.2, -2: -0.5}
FACTOR_NOTE = "MonPort: factors."
FRONT_FACTORS = {engine: front for front, engine in FACTOR_TARGETS.items()}

# Classes, régions, thématiques: Exclure (« exclure », 0 % exactement), Neutre (clé absente, libre pour l'optimiseur)
# ou un pourcentage saisi de 0 à 100, imposé EXACTEMENT.
# Classes: part du portefeuille total, tous les instruments admissibles, FNB compris; « crypto » = crypto détenue en
# direct (type Cryptocurrency, pas toute la classe Alternative).
# Régions et thématiques: part de la poche actions (actions en direct et FNB d'actions), tenue par les seules actions
# détenues en direct du groupe; un FNB n'y compte jamais (voir `config.EQUITY_SLEEVE_CLASSES`).
EXCLUDE = "exclure"
CRYPTO_TYPE = "Cryptocurrency"

LOSS_BY_REACTION = {0: 10.0, 1: 15.0, 2: 25.0, 3: 35.0}  # baisse de 20 %: je vends tout … j'investis plus
OBJECTIVES = {"securiser": "preservation", "fructifier": "balanced", "viser-haut": "growth"}
EXPERIENCE = {1: "none", 2: "basic", 3: "intermediate", 4: "advanced", 5: "advanced"}
FEES = {"ETF": 0.002}  # faute de donnée: 0,20 % par FNB, rien pour un titre détenu en direct
LINE_CAP = 0.40  # limite de sécurité: aucune ligne au-delà de 40 %
MAX_ADJUSTMENT = 1000

# Répartition stratégique du profil (portefeuilles modèles 20/80 … 100/0): plancher d'obligations, fixé par le code
# pour les portefeuilles qui suivent le profil (« Ton profil », et les 3 variantes quand le profil est cohérent).
BOND_FLOOR = {"conservateur": 0.80, "modere": 0.60, "equilibre": 0.40, "dynamique": 0.20, "agressif": 0.0}
BOND_SHIFT = {"prudent": 0.0, "equilibre": 0.0, "conviction": 0.0}  # plus de décalage: seul A distingue les variantes
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
    present = {v.lower(): v for v in allowed.get(dimension, [])}
    return [present[c.lower()] for c in candidates if c.lower() in present]


def _preference_target(block: str, item: str, allowed: dict[str, list[str]]) -> tuple[Optional[str], list[str]]:
    """(dimension du moteur, libellés) d'un élément du questionnaire; (None, []) s'il n'a pas d'équivalent."""
    if block == "classes" and item == "crypto":
        present = {v.lower(): v for v in allowed.get("instrument_type", [])}
        return ("instrument_type", [present[CRYPTO_TYPE.lower()]]) if CRYPTO_TYPE.lower() in present else (None, [])
    if block == "themes" and item in THEME_TAGS:
        present = {v.lower(): v for v in allowed.get("theme", [])}
        tag = THEME_TAGS[item]
        return ("theme", [present[tag]]) if tag in present else (None, [])
    targets = _targets(block, item, allowed)
    return ({"classes": "asset_class", "regions": "country", "themes": "sector"}[block] if targets else None), targets


EXCLUDE_TYPES = {"asset_class": T.EXCLUDE_ASSET_CLASS, "instrument_type": T.EXCLUDE_INSTRUMENT_TYPE,
                 "country": T.EXCLUDE_COUNTRY, "sector": T.EXCLUDE_SECTOR, "theme": T.EXCLUDE_THEME}
EXACT_TYPES = {"asset_class": T.EXACT_ASSET_CLASS_WEIGHT, "instrument_type": T.EXACT_INSTRUMENT_TYPE_WEIGHT,
               "country": T.EXACT_COUNTRY_WEIGHT, "sector": T.EXACT_SECTOR_WEIGHT, "theme": T.EXACT_THEME_WEIGHT}
EXACT_DIMENSION = {t: d for d, t in EXACT_TYPES.items()}


def _dedupe(constraints: list[Constraint]) -> list[Constraint]:
    """Une exclusion l'emporte sur un plancher ou un plafond visé (ex.: FNB seulement et un plancher d'actions de
    Pépite); pour une même cible, on garde la contrainte la plus forte. Un pourcentage EXACT du client n'est jamais
    effacé par une exclusion: les deux restent, et le conflit est signalé (`detect_conflicts`)."""
    excluded = {(c.type.value.removeprefix("exclude_"), (c.target or "").lower()) for c in constraints
                if c.type.value.startswith("exclude_")}
    unique: dict[tuple[str, str], Constraint] = {}
    for c in constraints:
        dimension = c.type.value.removeprefix("min_").removeprefix("max_").removesuffix("_weight")
        bound = c.type.value.startswith(("min_", "max_"))
        if bound and (dimension, (c.target or "").lower()) in excluded:
            continue
        key = (c.type.value, (c.target or "").lower())
        if key not in unique or (c.hard and not unique[key].hard):
            unique[key] = c
    return list(unique.values())


def direct_types(allowed: dict[str, list[str]]) -> list[str]:
    """Les types d'instrument détenus en direct présents dans l'univers."""
    present = {v.lower(): v for v in allowed.get("instrument_type", [])}
    return [present[t.lower()] for t in DIRECT_TYPES if t.lower() in present]


def fund_types(allowed: dict[str, list[str]]) -> list[str]:
    """Les types d'instrument des FNB présents dans l'univers."""
    present = {v.lower(): v for v in allowed.get("instrument_type", [])}
    return [present[t.lower()] for t in FUND_TYPES if t.lower() in present]


def share_of(choice: Any) -> Optional[float]:
    """Le pourcentage saisi (0 à 100) converti en fraction (45 -> 0.45); None pour « exclure », neutre ou une valeur
    hors de [0, 100] ou non finie (jamais ramenée de force dans l'intervalle)."""
    if isinstance(choice, bool) or not isinstance(choice, (int, float)) or not math.isfinite(choice):
        return None
    return float(choice) / 100 if 0 <= choice <= 100 else None


def shown_classes(prefs: dict) -> list[str]:
    return SHOWN_CLASSES.get(str(prefs.get("vehicles")), [k for k in CLASSES if k != "liquidites"])


def factor_constraints(prefs: dict, allowed: dict[str, list[str]]) -> tuple[list[Constraint], list[str]]:
    """Échelle des facteurs -> exposition minimale ou maximale (z-score moyen des actions détenues en direct)."""
    chosen = {f: level for f, level in (prefs.get("factors") or {}).items() if level}
    if not chosen:
        return [], []
    if prefs.get("vehicles") == "fnb":
        return [], ["facteurs (ils ne visent que les actions détenues en direct, et tu as choisi FNB seulement)"]
    present = set(allowed.get("factor", []))
    out, skipped = [], []
    for item, level in chosen.items():
        factor = FACTOR_TARGETS.get(item)
        if factor not in present:
            skipped.append(f"facteur « {item} »")
            continue
        kind = T.MIN_FACTOR_EXPOSURE if level > 0 else T.MAX_FACTOR_EXPOSURE
        out.append(Constraint(type=kind, target=factor, value=FACTOR_LEVELS[level], hard=abs(level) == 2,
                              note=f"{FACTOR_NOTE}{item} = {level}"))
    return out, skipped


def is_exclusion(c: Constraint) -> bool:
    """Une exclusion du client, appliquée aux 3 profils: exclude_*, ou un facteur au niveau Exclure."""
    return c.type.value.startswith("exclude_") or (
        c.type is T.MAX_FACTOR_EXPOSURE and c.hard and (c.note or "").startswith(FACTOR_NOTE))


def preference_choice(choice: Any) -> dict[str, Any]:
    """Une réponse du questionnaire sous la forme interne {"mode": exclude | neutral | exact, "weight"}."""
    if choice == EXCLUDE:
        return {"mode": "exclude", "weight": None}
    share = share_of(choice)
    return {"mode": "neutral", "weight": None} if share is None else {"mode": "exact", "weight": share}


def preference_constraints(prefs: dict, allowed: dict[str, list[str]]) -> tuple[list[Constraint], list[str]]:
    """Traduit Exclure et les pourcentages saisis en contraintes dures (égalités). Neutre n'ajoute rien.
    Retourne aussi ce qui n'a pas pu l'être (élément sans équivalent dans l'univers, valeur illisible)."""
    out: list[Constraint] = []
    skipped: list[str] = []
    for block in ("classes", "regions", "themes"):
        for item, choice in (prefs.get(block) or {}).items():
            pref = preference_choice(choice)
            if pref["mode"] == "neutral":
                if choice is not None and choice != "neutre":
                    skipped.append(f"{BLOCK_LABELS[block]} « {item} » (valeur {choice!r} illisible, laissée neutre)")
                continue
            if block == "classes" and item not in shown_classes(prefs):
                continue
            dimension, targets = _preference_target(block, item, allowed)
            if not targets:
                skipped.append(f"{BLOCK_LABELS[block]} « {item} »")
                continue
            note = f"MonPort: {block}.{item} = {choice}"
            if pref["mode"] == "exclude":
                out += [Constraint(type=EXCLUDE_TYPES[dimension], target=t, hard=True, note=note) for t in targets]
                continue
            # Une région ou une thématique sectorielle réunit plusieurs pays ou secteurs: un seul groupe, une égalité.
            out.append(Constraint(type=EXACT_TYPES[dimension], target=SEP.join(targets), value=round(pref["weight"], 6),
                                  hard=True, note=note))
    factors_out, factors_skipped = factor_constraints(prefs, allowed)
    out += factors_out
    skipped += factors_skipped

    vehicles = prefs.get("vehicles")
    if vehicles == "fnb":
        out += [Constraint(type=T.EXCLUDE_INSTRUMENT_TYPE, target=t, hard=True, note="MonPort: FNB seulement")
                for t in direct_types(allowed)]
    elif vehicles == "titres":
        out += [Constraint(type=T.EXCLUDE_INSTRUMENT_TYPE, target=t, hard=True, note="MonPort: titres individuels seulement")
                for t in fund_types(allowed)]
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


def preference_contradictions(prefs: dict) -> list[str]:
    """Choix du questionnaire impossibles à respecter ensemble, détectés avant toute optimisation.

    Le code ne contourne jamais un pourcentage du client: ces cas sont signalés, pas corrigés en silence. Les
    pourcentages de dimensions différentes se chevauchent (une action canadienne de technologie compte dans les deux):
    ils ne sont additionnés qu'à l'intérieur des régions, qui sont disjointes, et des classes. Régions et thématiques
    sont des parts de la poche actions: elles ne se comparent pas au pourcentage d'actions du portefeuille.
    """
    vehicles = prefs.get("vehicles")
    classes = prefs.get("classes") or {}
    exact = {b: {k: share_of(v) for k, v in (prefs.get(b) or {}).items() if share_of(v) is not None}
             for b in ("classes", "regions", "themes")}
    stock_targets = {**{f"région « {k} »": v for k, v in exact["regions"].items() if v > 0},
                     **{f"thématique « {k} »": v for k, v in exact["themes"].items() if v > 0}}
    out = []
    if vehicles == "fnb":
        if exact["classes"].get("crypto"):
            out.append("FNB seulement exclut la crypto détenue en direct : la part de crypto demandée est impossible.")
        for name, v in stock_targets.items():
            out.append(f"FNB seulement ne permet aucune action en direct, et les FNB ne comptent pas pour la "
                       f"{name} : {v:.0%} est impossible.")
    if vehicles == "titres":
        for k, v in exact["classes"].items():
            if v > 0 and k not in shown_classes(prefs):
                out.append(f"Titres individuels seulement : aucun titre de la classe {CLASS_LABELS.get(k, k).lower()} "
                           f"n'est disponible, {v:.0%} est impossible.")
    stocks_out = classes.get("actions") == EXCLUDE or exact["classes"].get("actions") == 0
    if stocks_out and stock_targets:
        out.append("Les actions sont exclues, mais une région ou une thématique demande des actions en direct.")
    for block in ("classes", "regions"):
        total = sum(exact[block].values())
        if total > 1 + 1e-9:
            out.append(f"Les pourcentages des {BLOCK_LABELS[block]}s totalisent {total:.0%}, plus que 100 %.")
    return out


def coherence_facts(profile: dict, prefs: dict) -> list[str]:
    score, classes = risk_score(profile), prefs.get("classes") or {}
    crypto, actions = share_of(classes.get("crypto")), share_of(classes.get("actions"))
    out = []
    if score < 40 and crypto:
        out.append("Tu cherches plutôt de la stabilité, mais tu demandes des crypto-actifs. Les deux se marient mal : "
                   "la crypto peut perdre la moitié de sa valeur en quelques mois.")
    if score < 40 and actions is not None and actions >= 0.7:
        out.append("Mettre autant d’actions avec un profil prudent peut te faire vivre des baisses difficiles à supporter.")
    if score > 65 and (classes.get("actions") == EXCLUDE or (actions is not None and actions <= 0.3)):
        out.append("Ton profil est dynamique, mais tu limites les actions : le rendement attendu sera plus faible que ce "
                   "que ton horizon permet.")
    if score < 77 and prefs.get("vehicles") == "titres":  # sous « agressif », le profil prévoit des obligations
        out.append("Avec des titres individuels seulement, ton portefeuille n’aura pas d’obligations : ton profil en "
                   "prévoit pourtant une part pour amortir les baisses.")
    kept = [k for k in shown_classes(prefs) if classes.get(k) != EXCLUDE and share_of(classes.get(k)) != 0]
    if len(kept) == 1:
        out.append(f"Tu n’as gardé qu’un seul type de placement ({CLASS_LABELS[kept[0]].lower()}) : ton portefeuille sera "
                   "très peu diversifié.")
    return out + preference_contradictions(prefs)


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
    """Plafond de volatilité d'un gestionnaire. Profil cohérent: le MÊME pour les 3 variantes (celui du profil),
    seul A les distingue. Profil incohérent: celui du profil, sauf « Tes préférences » qui n'en a pas."""
    s = slot_position(check, slot)
    if s is None:
        return None
    return round(_interpolate(check.risk_position if check.coherent else s, VOL_ANCHORS), 3)


# --------------------------------------------------------------------------- #
# Profils de contraintes: Pépite propose, le code valide
# --------------------------------------------------------------------------- #
def _limits(vol: float, weight: float) -> list[Constraint]:
    """Limites du profil: volatilité, et poids par titre détenu en direct (un FNB n'est plafonné qu'à 40 %)."""
    return [Constraint(type=T.MAX_VOLATILITY, value=round(vol, 3), hard=True, note="Limite du profil"),
            Constraint(type=T.MAX_STOCK_WEIGHT, value=round(min(weight, LINE_CAP), 3), hard=True, note="Limite du profil"),
            Constraint(type=T.MAX_POSITION_WEIGHT, value=LINE_CAP, hard=True, note="Limite de sécurité")]


def follow_profile(constraints: list[Constraint], floor: float, risk_label: str,
                   allowed: dict[str, list[str]], fixed: Iterable[str] = ()) -> list[Constraint]:
    """Impose la répartition du profil: la part d'obligations et, pour un profil prudent, pas de crypto.
    Ces règles remplacent les poids que les préférences visaient sur les mêmes classes; une exclusion des
    obligations par le client l'emporte sur le plancher, comme une classe dont il a fixé le pourcentage (`fixed`)."""
    present = {v.lower(): v for v in allowed["asset_class"]}
    fixed = {t.lower() for t in fixed}
    bonds = next((present[t.lower()] for t in BOND_TARGETS if t.lower() in present), None)
    cryptos = [present[t.lower()] for t in CRYPTO_TARGETS if t.lower() in present] if risk_label in NO_CRYPTO else []
    # Une part de crypto fixée par le client (type Cryptocurrency) l'emporte sur « pas de crypto » du profil.
    cryptos = [] if CRYPTO_TYPE.lower() in fixed else [t for t in cryptos if t.lower() not in fixed]
    excluded = {(c.target or "").lower() for c in constraints if c.type is T.EXCLUDE_ASSET_CLASS}
    # Le plancher se loge dans la place que les pourcentages du client laissent libre.
    floor = min(floor, 1 - sum(c.value or 0 for c in constraints
                                if c.type in (T.EXACT_ASSET_CLASS_WEIGHT, T.MIN_ASSET_CLASS_WEIGHT) and c.hard
                                and (c.target or "").lower() in fixed))
    if bonds and (floor <= 0 or bonds.lower() in excluded or bonds.lower() in fixed):
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


def _family(c: Constraint) -> str:
    """« sector_share », « asset_class_weight »…: plancher, plafond et poids exact d'une même cible forment une famille."""
    return c.type.value.removeprefix("min_").removeprefix("max_").removeprefix("exact_")


def impose_targets(constraints: list[Constraint], targets: list[Constraint]) -> list[Constraint]:
    """Les pourcentages saisis par le client remplacent ce que Pépite a écrit sur les mêmes cibles."""
    keys = {(_family(c), (c.target or "").lower()) for c in targets}
    return [c for c in constraints if (_family(c), (c.target or "").lower()) not in keys] + targets


def fallback_plan(check: PepiteCheck, prefs: list[Constraint]) -> dict[str, tuple[str, list[Constraint]]]:
    """Profils écrits par le code si Pépite échoue ou si l'un des siens est inutilisable."""
    vol, weight = check.suggested_max_volatility, check.suggested_max_position_weight
    exclusions = [c for c in prefs if is_exclusion(c)]
    if check.coherent:
        return {
            # Mêmes contraintes pour les trois; seule l'aversion au risque A change (S − 0,10 / S / S + 0,10).
            "prudent": ("Tes réponses, avec une aversion au risque un cran plus élevée.", prefs + _limits(vol, weight)),
            "equilibre": ("Fidèle à tes réponses.", prefs + _limits(vol, weight)),
            "conviction": ("Tes réponses, avec une aversion au risque un cran plus faible.", prefs + _limits(vol, weight)),
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
    """Incohérent: seul « Ton profil » suit la répartition du profil. Cohérent: le MÊME plancher pour les 3 variantes
    (plus de décalage de ±10 points: seul A distingue les variantes)."""
    base = BOND_FLOOR.get(check.risk_label, 0.0)
    if not check.coherent:
        return {"prudent": base}
    return {s: base for s in SLOTS}


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


def _floor_column(c: Constraint) -> Optional[str]:
    """La colonne d'un poids minimal par groupe (secteur, pays, classe d'actifs); None pour les autres contraintes."""
    if not (c.type.value.startswith("min_") and c.target):
        return None
    return DIMENSION_COLUMN.get(c.type.value.removeprefix("min_").removesuffix("_weight"))


def drop_unreachable_floors(market: Market, constraints: list[Constraint]) -> tuple[list[Constraint], Optional[str]]:
    """Retire un poids minimal qu'aucun placement admissible ne peut remplir. Ex.: « FNB seulement » et plus de
    techno, alors qu'un FNB n'a pas de secteur. Sans ça, les trois gestionnaires échouent."""
    hard = [c for c in constraints if c.hard]
    eligible = market.assets[~excluded_mask(market, hard)]
    dropped = []
    stocks = eligible[eligible["instrument_type"].astype(str).str.lower() == "stock"]
    for c in hard:
        column = _floor_column(c)
        if column and not (eligible[column].astype(str).str.lower() == c.target.lower()).any():
            dropped.append(c)
        elif c.type in SHARE_TYPES and SHARE_TYPES[c.type][1] == "min" and (c.value or 0) > 0:
            share_column = DIMENSION_COLUMN[SHARE_TYPES[c.type][0]]
            members = {t.lower() for t in share_targets(c)}
            if not stocks[share_column].astype(str).str.lower().isin(members).any():
                dropped.append(c)
    if not dropped:
        return constraints, None
    names = ", ".join(f"« {', '.join(share_targets(c))} »" for c in dropped)
    note = f"Avec tes choix, aucun placement ne correspond à {names} : je n’ai pas pu en garantir une part."
    return [c for c in constraints if c not in dropped], note


def ensure_feasible(market: Market, constraints: list[Constraint]) -> tuple[list[Constraint], Optional[str]]:
    """Retire les poids minimaux impossibles, puis relève le plafond de volatilité quand l'univers ne permet pas de
    descendre aussi bas: sans ça, le gestionnaire et son repli échouent tous les deux (fréquent sur le dataset
    synthétique pour un profil prudent)."""
    constraints, floor_note = drop_unreachable_floors(market, constraints)
    constraints, vol_note = _raise_volatility_cap(market, constraints)
    return constraints, " ".join(n for n in (floor_note, vol_note) if n) or None


def _raise_volatility_cap(market: Market, constraints: list[Constraint]) -> tuple[list[Constraint], Optional[str]]:
    hard = [c for c in constraints if c.hard]
    caps = [c.value for c in hard if c.type is T.MAX_VOLATILITY and c.value]
    if not caps:
        return constraints, None
    eligible = market.assets[~excluded_mask(market, hard)]
    picks = eligible.sort_values("ann_vol").index[:24].tolist()
    # Les contraintes de facteurs exigent des actions qui les respectent: les moins volatiles d'entre elles.
    picks += eligible.loc[factor_fits(eligible, hard)].sort_values("ann_vol").index[:8].tolist()
    for c in hard:  # les poids minimaux exigent des titres de leur groupe
        if column := _floor_column(c):
            group = eligible[eligible[column].astype(str).str.lower() == c.target.lower()]
            picks += group.sort_values("sharpe", ascending=False).index[:3].tolist()
        elif c.type in SHARE_TYPES and SHARE_TYPES[c.type][1] == "min":
            members = {t.lower() for t in share_targets(c)}
            group = eligible[(eligible["instrument_type"].astype(str).str.lower() == "stock")
                             & eligible[DIMENSION_COLUMN[SHARE_TYPES[c.type][0]]].astype(str).str.lower().isin(members)]
            picks += group.sort_values("sharpe", ascending=False).index[:3].tolist()
        elif c.type in EXACT_DIMENSION and (c.value or 0) > 0:  # un pourcentage exact exige des titres du groupe
            dimension = EXACT_DIMENSION[c.type]
            exposed = [s for s, row in eligible.iterrows() if preference_exposure(s, row, dimension, c.target or "")]
            picks += eligible.loc[exposed].sort_values("sharpe", ascending=False).index[:5].tolist()
    picks = list(dict.fromkeys(picks))[: get_runtime_settings().max_assets_per_portfolio]
    others = [c for c in constraints if not (c.hard and c.type is T.MAX_VOLATILITY)]
    lowest = optimize(market, picks, "min_volatility", others)
    if not lowest.ok or not lowest.metrics or lowest.metrics.volatility <= min(caps):
        return constraints, None
    cap = math.ceil((lowest.metrics.volatility + 0.003) * 100) / 100
    note = "L’univers de placements ne permet pas un risque aussi bas que demandé : j’ai visé le plus bas possible."
    return others + [Constraint(type=T.MAX_VOLATILITY, value=cap, hard=True, note="Plafond relevé au plus bas possible")], note


def build_profiles(plan: Optional[ConstraintPlan], check: PepiteCheck, prefs: list[Constraint],
                   allowed: dict[str, list[str]], impose: bool = True) -> tuple[dict[str, tuple[str, list[Constraint]]], int]:
    """Retourne les 3 profils par slot et le nombre de profils remplacés par ceux du code.

    `impose`: les pourcentages du questionnaire remplacent ceux de Pépite dans les profils qui suivent les préférences.
    Faux pour une relance du chat, où Pépite réécrit elle-même ce que le client a changé."""
    fallback = fallback_plan(check, prefs)
    floors = bond_floors(check)
    exclusions = [c for c in prefs if is_exclusion(c)]
    # Tout le reste du questionnaire: pourcentages et facteurs, imposés tels quels.
    targets = [c for c in prefs if not is_exclusion(c)]
    proposed = {p.slot: p for p in (plan.profiles if plan else [])}
    if check.coherent and "equilibre" in proposed:
        # Mêmes contraintes pour les 3 variantes: le profil « fidèle » de Pépite (qui intègre l'ajustement libre du
        # client) sert aux trois. Seul A, tiré de S − 0,10 / S / S + 0,10, les distingue.
        common = proposed["equilibre"]
        proposed = {s: common.model_copy(update={"slot": s, "rationale": proposed.get(s, common).rationale})
                    for s in SLOTS}
    out, replaced = {}, 0
    for slot in SLOTS:
        p = proposed.get(slot)
        # « Ton profil » (incohérent) ignore les préférences; partout ailleurs, elles comptent pour de vrai.
        follows = check.coherent or slot != "prudent"
        raw = impose_targets(p.constraints, targets) if p and impose and follows else p.constraints if p else None
        constraints = validate_profile(raw, exclusions, allowed) if raw is not None else None
        rationale = p.rationale if p else ""
        if constraints is None:
            replaced += 1
            rationale, raw = fallback[slot]
            constraints = validate_profile(raw, exclusions, allowed) or _limits(check.suggested_max_volatility, LINE_CAP)
        # Le plafond par titre du profil, si Pépite l'a oublié (sauf « Tes préférences », qui ignore le profil).
        if (check.coherent or slot != "conviction") and not any(c.type is T.MAX_STOCK_WEIGHT for c in constraints):
            cap = min(check.suggested_max_position_weight, LINE_CAP)
            constraints = constraints + [Constraint(type=T.MAX_STOCK_WEIGHT, value=cap, hard=True, note="Limite du profil")]
        if follows:
            constraints = promote_preferences(constraints)
        if slot in floors:
            # Une classe dont le client a fixé le pourcentage garde son pourcentage, plancher d'obligations compris.
            fixed = [c.target for c in targets if c.target
                     and _family(c) in ("asset_class_weight", "instrument_type_weight")] if follows else []
            constraints = follow_profile(constraints, floors[slot], check.risk_label, allowed, fixed)
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
    # Mêmes champs que RiskNote dans frontend/src/types.ts.
    warnings = [{"title": w["title"], "detail": w["detail"], "severity": w["severity"]}
                for w in (risk_report or {}).get("warnings", [])
                if w.get("portfolio_id") == p.id and w.get("severity") in ("medium", "high")]
    agent_notes = [t for t in (p.summary, p.tradeoffs, verdict.comment if verdict else None) if t] + extra
    if skipped:
        agent_notes.append(f"Pas encore pris en compte par les agents : {', '.join(skipped)}.")
    if verdict and not verdict.compliant:
        warnings.insert(0, {"title": "Certaines de tes limites ne sont pas respectées",
                            "detail": "Lis les détails avant de choisir ce portefeuille.", "severity": "high"})
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
        "factors": factor_view(p),
    }


def factor_view(p: Portfolio) -> dict:
    """Expositions aux facteurs et actions notées (FactorView de frontend/src/types.ts), identifiants du frontend."""
    weights = {pos.symbol: pos.weight for pos in p.positions}
    exposure, coverage = factors.exposures(weights)
    scores = factors.scores_for(weights)
    names = {pos.symbol: pos.name for pos in p.positions}
    stocks = [{"ticker": s, "name": names[s], "weight": weights[s],
               "scores": {FRONT_FACTORS[f]: round(float(scores.at[s, f]), 2) for f in factors.FACTORS}}
              for s in sorted(scores.index, key=lambda s: -weights[s])]
    return {"coverage": coverage, "exposure": {FRONT_FACTORS[f]: v for f, v in exposure.items()}, "stocks": stocks}


# --------------------------------------------------------------------------- #
# Événements: bus des agents -> PipelineEvent
# --------------------------------------------------------------------------- #
TOOL_TEXT = {
    "describe_universe": "tour d’horizon des placements",
    "screen_assets": "recherche de placements",
    "screen_factor": "recherche d’actions selon tes styles",
    "optimize_portfolio": "calcul des poids",
    "get_latest_macro_snapshot": "lecture du contexte économique",
    "get_macro_history": "comparaison avec des périodes passées",
}


def status(agent: str, state: str, message: str) -> dict:
    return {"type": "agent_status", "agent": agent, "status": state, "message": message}


def pepite(text: str) -> dict:
    return {"type": "pepite", "text": text}


class Translator:
    """Les statuts des agents deviennent des cartes: gestionnaire-<slot>, juge-<slot>, juge-final, risques.
    Les événements « front » sont émis tels quels par l'orchestration (carte Pépite, portefeuilles…). Pépite décrit
    elle-même ce qu'elle fait (événements « front »): ses propres événements d'agent ne passent pas ici."""

    def __init__(self) -> None:
        self.slots: dict[str, str] = {}  # nom de mandat -> slot, rempli quand les profils sont prêts

    def translate(self, e: dict) -> Iterable[dict]:
        kind, agent, state = e.get("type"), e.get("agent") or "", e.get("state")
        if kind == "front":
            yield e["event"]
        elif kind == "heartbeat":
            yield {"type": "heartbeat"}
        elif e.get("step") == "chat":  # une question posée après coup ne touche pas aux cartes du pipeline
            return
        elif agent == "Juge final":
            if state == "start":
                yield status("juge-final", "running", "Comparaison des 3 portefeuilles…")
        elif agent.startswith("Risque "):
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


def front(bus: EventBus, event: dict) -> None:
    bus.emit("front", event=event)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _questionnaire(payload: dict) -> tuple[dict, dict]:
    """Le JSON du questionnaire, sans les ajouts prévus (jamais envoyés aux agents)."""
    return payload.get("profile") or {}, payload.get("constraints") or {}


# --------------------------------------------------------------------------- #
# Flux SSE (les points d'entrée sont dans workflow/flow.py)
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
