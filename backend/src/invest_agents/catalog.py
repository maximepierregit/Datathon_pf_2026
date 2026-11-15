"""Catalogue de contraintes des agents, et pont vers le moteur financier (`constraints.py`).

Deux rôles, volontairement dans le même module parce qu'ils forment un seul contrat:

1. **Le vocabulaire des agents.** Les LLM et le frontend manipulent des `Constraint` (`schemas.ConstraintType`:
   exclure un secteur, poids maximal par titre, plancher d'obligations…). Le moteur, lui, prend un dictionnaire de
   réglages (`config.get_agent_settings`) et un univers pandas. Ce module valide les contraintes contre le catalogue
   réel du dataset, les fusionne, détecte les conflits et les décrit en français.
2. **La traduction vers le moteur.** `agent_request()` transforme une liste de `Constraint` en requête agent;
   `screen()`, `plan_for()` et `audit()` délèguent au moteur l'admissibilité, les bornes, les contraintes linéaires,
   le budget, les titres requis, le minimum de 1 % et la vérification après résolution.

INVARIANT CONSERVÉ: les agents proposent, le code garantit. Aucun chiffre de ce module ne vient d'un modèle.

DEUX CHOIX DE TRADUCTION, À CONNAÎTRE
- **Secteur et pays passent par les symboles, pas par les dimensions économiques du moteur.** Le moteur est
  volontairement strict: dès qu'une restriction porte sur `sector`, `country`, `region`, `industry` ou `factor`, il
  rejette tout instrument dont l'exposition n'est pas démontrée, donc tous les FNB (leur secteur vaut « Non classé »
  dans le Parquet, faute de look-through). Mesuré sur le dataset réel: une seule exclusion sectorielle fait tomber
  l'univers de 801 à 668 actifs, en retirant les 81 FNB et les 2 cryptos; « FNB seulement » plus une exclusion
  sectorielle ne laisse aucun actif. Comme les 12 seuls actifs à revenu fixe de l'univers sont des FNB, un profil
  prudent (plancher d'obligations) deviendrait infaisable dès que le client exclut un thème.
  Ce module résout donc « exclure le secteur Energy » en la liste des titres de ce secteur (`excluded_symbols`), une
  dimension dont le moteur garantit l'exposition. Le résultat est identique à l'ancien comportement, sans affaiblir
  la garantie du moteur: un FNB compte pour 0 dans un plafond sectoriel, faute de données. Pour appliquer la règle
  stricte, fournir un look-through vérifié (`exposure_overrides`) et viser les dimensions économiques directement.
- **Les niveaux `less`/`more`/`require` du moteur ne sont pas utilisés.** Ils exigent une calibration absente de
  `config.py` (`soft_penalty_strength`, `reference_allocation_source`, `require_group_min_weight` valent None) et
  feraient échouer `assert_ready_for_optimization`. Les préférences de MonPort arrivent ici déjà chiffrées
  (`monport.preference_constraints`), donc en plafonds et planchers explicites.

Le cash synthétique (`CASH-CAD`) est désactivé: il est absent du Parquet, donc `Market.moments()` ne saurait pas
l'évaluer. Les liquidités existent déjà dans l'univers sous forme de FNB monétaires.
"""

from __future__ import annotations

import dataclasses
import difflib
import logging
import math
from dataclasses import dataclass
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

from . import factors
from .config import INSTRUMENT_SELECTION, RISK_AVERSION, get_agent_settings
from .constraints import (
    ConstraintError,
    ConstraintInfeasibleError,
    ConstraintPlan,
    GroupConstraint,
    ScreeningResult,
    build_constraint_plan,
    check_linear_feasibility,
    filter_eligible_universe,
    preference_exposure,
    validate_weights,
)
from .market import UNKNOWN, Market
from .schemas import Constraint, ConstraintCheck, ConstraintRef, ConstraintType as T

logger = logging.getLogger(__name__)

TOL = 1e-3  # tolérance numérique sur la volatilité et le rendement
WTOL = 2e-4  # tolérance sur les poids (les poids sont arrondis à 4 décimales)
HELD = 5e-4  # poids à partir duquel une position est considérée comme détenue


# --------------------------------------------------------------------------- #
# Vocabulaire des agents
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Spec:
    dimension: Optional[str]  # sector | country | asset_class | instrument_type | symbol | None
    kind: str  # fraction | count | none
    direction: Optional[str]  # max | min | None
    description: str


SPECS: dict[T, Spec] = {
    T.MAX_POSITION_WEIGHT: Spec(None, "fraction", "max", "Poids maximal d'un titre (0.10 = 10 %)"),
    T.MAX_STOCK_WEIGHT: Spec(None, "fraction", "max", "Poids maximal d'un titre détenu en direct, hors FNB (0.10 = 10 %)"),
    T.MIN_POSITIONS: Spec(None, "count", "min", "Nombre minimal de positions"),
    T.MAX_POSITIONS: Spec(None, "count", "max", "Nombre maximal de positions"),
    T.MAX_VOLATILITY: Spec(None, "fraction", "max", "Volatilité annualisée maximale du portefeuille (0.12 = 12 %)"),
    T.MIN_EXPECTED_RETURN: Spec(None, "fraction", "min", "Rendement annualisé historique minimal (0.06 = 6 %)"),
    T.EXCLUDE_SECTOR: Spec("sector", "none", None, "Exclure un secteur"),
    T.EXCLUDE_COUNTRY: Spec("country", "none", None, "Exclure un pays"),
    T.EXCLUDE_ASSET_CLASS: Spec("asset_class", "none", None, "Exclure une classe d'actifs"),
    # Une classe d'actifs mélange titres et FNB (« Equity » = actions et FNB d'actions): « FNB seulement » passe par ici.
    T.EXCLUDE_INSTRUMENT_TYPE: Spec("instrument_type", "none", None,
                                    "Exclure un type d'instrument (Stock = action détenue en direct, Cryptocurrency = "
                                    "crypto détenue en direct, ETF = FNB)"),
    T.EXCLUDE_SYMBOL: Spec("symbol", "none", None, "Exclure un titre"),
    T.MAX_SECTOR_WEIGHT: Spec("sector", "fraction", "max", "Poids maximal d'un secteur"),
    T.MIN_SECTOR_WEIGHT: Spec("sector", "fraction", "min", "Poids minimal d'un secteur"),
    T.MAX_COUNTRY_WEIGHT: Spec("country", "fraction", "max", "Poids maximal d'un pays"),
    T.MIN_COUNTRY_WEIGHT: Spec("country", "fraction", "min", "Poids minimal d'un pays"),
    T.MAX_ASSET_CLASS_WEIGHT: Spec("asset_class", "fraction", "max", "Poids maximal d'une classe d'actifs"),
    T.MIN_ASSET_CLASS_WEIGHT: Spec("asset_class", "fraction", "min", "Poids minimal d'une classe d'actifs"),
    T.MAX_SYMBOL_WEIGHT: Spec("symbol", "fraction", "max", "Poids maximal d'un titre précis"),
    T.MIN_SYMBOL_WEIGHT: Spec("symbol", "fraction", "min", "Poids minimal d'un titre précis (le détenir)"),
    T.MIN_SECTOR_SHARE: Spec("sector", "fraction", "min",
                             "Part minimale de la poche actions dans un ou plusieurs secteurs"),
    T.MAX_SECTOR_SHARE: Spec("sector", "fraction", "max",
                             "Part maximale de la poche actions dans un ou plusieurs secteurs"),
    T.MIN_COUNTRY_SHARE: Spec("country", "fraction", "min",
                              "Part minimale de la poche actions dans un ou plusieurs pays"),
    T.MAX_COUNTRY_SHARE: Spec("country", "fraction", "max",
                              "Part maximale de la poche actions dans un ou plusieurs pays"),
    # Exposition = moyenne des z-scores des actions détenues en direct, pondérée par leur poids (voir factors.py).
    T.MIN_FACTOR_EXPOSURE: Spec("factor", "score", "min",
                                "Exposition minimale à un facteur, en écarts-types (0.5 = actions en moyenne un "
                                "demi écart-type au-dessus de leur secteur)"),
    T.MAX_FACTOR_EXPOSURE: Spec("factor", "score", "max",
                                "Exposition maximale à un facteur, en écarts-types (-0.2 = légèrement sous la moyenne)"),
    T.EXCLUDE_THEME: Spec("theme", "none", None, "Exclure une thématique (actions détenues en direct seulement)"),
    T.EXACT_ASSET_CLASS_WEIGHT: Spec("asset_class", "fraction", "exact",
                                     "Poids exact d'une classe d'actifs, FNB compris (0.30 = exactement 30 %)"),
    T.EXACT_INSTRUMENT_TYPE_WEIGHT: Spec("instrument_type", "fraction", "exact",
                                         "Poids exact d'un type d'instrument (Cryptocurrency = crypto détenue en direct)"),
    T.EXACT_COUNTRY_WEIGHT: Spec("country", "fraction", "exact",
                                 "Part exacte de la poche actions tenue par les actions détenues en direct d'un ou "
                                 "plusieurs pays (0.30 = 30 % de la poche; les FNB d'actions sont dans la poche, "
                                 "jamais dans le groupe)"),
    T.EXACT_SECTOR_WEIGHT: Spec("sector", "fraction", "exact",
                                "Part exacte de la poche actions tenue par les actions détenues en direct d'un ou "
                                "plusieurs secteurs"),
    T.EXACT_THEME_WEIGHT: Spec("theme", "fraction", "exact",
                               "Part exacte de la poche actions tenue par les actions détenues en direct d'une ou "
                               "plusieurs thématiques"),
}
FACTOR_TYPES = {T.MIN_FACTOR_EXPOSURE, T.MAX_FACTOR_EXPOSURE}
# Pourcentages exacts du questionnaire -> dimension du moteur (`config.agent_preferences`).
EXACT_TYPES = {
    T.EXACT_ASSET_CLASS_WEIGHT: "asset_class",
    T.EXACT_INSTRUMENT_TYPE_WEIGHT: "instrument_type",
    T.EXACT_COUNTRY_WEIGHT: "country",
    T.EXACT_SECTOR_WEIGHT: "sector",
    T.EXACT_THEME_WEIGHT: "theme",
}
MULTI_TARGET_TYPES = {T.EXACT_COUNTRY_WEIGHT, T.EXACT_SECTOR_WEIGHT, T.EXACT_THEME_WEIGHT}
# Exclusions confiées au moteur comme préférences « exclude » des actions détenues en direct.
STOCK_EXCLUSIONS = {T.EXCLUDE_SECTOR: "sector", T.EXCLUDE_COUNTRY: "country", T.EXCLUDE_THEME: "theme"}
EXACT_TOL = 1e-3  # 0,1 point: les poids sont arrondis à 4 décimales, un groupe en somme plusieurs
SCORE_RANGE = 3.0  # une exposition au-delà de ±3 écarts-types n'a pas de sens
FACTOR_SLEEVE_MIN = 0.10  # avec une contrainte de facteur, au moins 10 % en actions notées (sinon 0 action la respecte)
FACTOR_MARGIN = 0.01  # l'optimiseur vise un peu au-delà du seuil: les poids sont ensuite arrondis à 4 décimales
FTOL = 0.01  # tolérance sur une exposition à un facteur

ANY = "*"  # cible générique: « chaque secteur » / « chaque pays » (plafonds seulement)
WILDCARD_TYPES = {T.MAX_SECTOR_WEIGHT, T.MAX_COUNTRY_WEIGHT}
# Parts de la poche actions (actions détenues en direct + FNB d'actions): 0.45 = 45 % de cette poche. Seules les
# actions en direct comptent au numérateur: un FNB n'a ni secteur ni pays connu, il compte comme hors du groupe. Il ne
# peut donc pas servir à contourner la part, contrairement à une base limitée aux actions en direct (mesuré: avec
# cette base, l'optimiseur gardait 0 action et satisfaisait la part à vide).
SHARE_TYPES = {
    T.MIN_SECTOR_SHARE: ("sector", "min"),
    T.MAX_SECTOR_SHARE: ("sector", "max"),
    T.MIN_COUNTRY_SHARE: ("country", "min"),
    T.MAX_COUNTRY_SHARE: ("country", "max"),
}
SEP = "|"  # plusieurs cibles pour une part (une région = plusieurs pays)
EQUITY_CLASSES = {"equity", "equities"}

DIMENSION_COLUMN = {"sector": "sector", "country": "country", "asset_class": "asset_class",
                    "instrument_type": "instrument_type", "theme": "theme", "symbol": None}
DIMENSION_FR = {"sector": "secteur", "country": "pays", "asset_class": "classe d'actifs",
                "instrument_type": "type d'instrument", "symbol": "titre", "factor": "facteur",
                "theme": "thématique"}

# Types traduits en contraintes linéaires de groupe, par dimension du moteur.
GROUP_TYPES = {
    T.MAX_ASSET_CLASS_WEIGHT: ("asset_class", "max"),
    T.MIN_ASSET_CLASS_WEIGHT: ("asset_class", "min"),
    T.MAX_SECTOR_WEIGHT: ("sector", "max"),
    T.MIN_SECTOR_WEIGHT: ("sector", "min"),
    T.MAX_COUNTRY_WEIGHT: ("country", "max"),
    T.MIN_COUNTRY_WEIGHT: ("country", "min"),
}
# Le moteur garantit l'exposition d'un FNB sur ces dimensions: elles peuvent lui être confiées directement.
ENGINE_DIMENSIONS = {"asset_class"}


# --------------------------------------------------------------------------- #
# Catalogue présenté aux agents
# --------------------------------------------------------------------------- #
def catalog_prompt(allowed: dict[str, list[str]]) -> str:
    """Texte décrivant le catalogue de contraintes, pour les prompts (Pépite, Extraction)."""
    lines = ["TYPES DE CONTRAINTES DISPONIBLES (champ `type`):"]
    for t, spec in SPECS.items():
        target = f" | cible: {DIMENSION_FR[spec.dimension]}" if spec.dimension else ""
        kind = {"fraction": " | valeur: fraction 0-1", "count": " | valeur: entier",
                "score": " | valeur: écarts-types entre -3 et 3", "none": ""}[spec.kind]
        lines.append(f"- {t.value}: {spec.description}{target}{kind}")
    lines += [
        "",
        "Pour max_sector_weight et max_country_weight, la cible \"*\" signifie « chaque secteur » ou « chaque pays » "
        "(ex.: « pas plus de 25 % par secteur »). Pour un secteur ou un pays précis, utilise son libellé.",
        "Les *_share se calculent sur la poche actions, actions en direct et FNB d'actions (0.45 = 45 % de cette "
        "poche); seules les actions en direct du groupe comptent pour la part. Leur cible accepte plusieurs libellés "
        "séparés par « | ».",
        "Les exact_*_weight sont des égalités (0.45 = exactement 45 %). Classe d'actifs et type d'instrument: part du "
        "portefeuille total. Pays, secteur et thématique: part de la poche actions (actions en direct et FNB "
        "d'actions), tenue par les seules actions détenues en direct du groupe; leur cible accepte « | ».",
        "",
        "VALEURS ACCEPTÉES POUR LES CIBLES (utiliser exactement ces libellés):",
        f"- sector: {', '.join(allowed['sector'])}",
        f"- country: {', '.join(allowed['country'])}",
        f"- asset_class: {', '.join(allowed['asset_class'])}",
        f"- instrument_type: {', '.join(allowed['instrument_type'])}",
        "- symbol: symbole boursier exact (utiliser l'outil search_universe pour retrouver un symbole à partir d'un nom)",
    ]
    if allowed.get("theme"):
        lines.append(f"- theme: {', '.join(allowed['theme'])}")
    if allowed.get("factor"):
        lines += [
            f"- factor: {', '.join(allowed['factor'])} (small_cap = petites capitalisations)",
            "",
            "Une exposition à un facteur ne porte que sur les actions détenues en direct (les FNB n'ont pas de score). "
            "Elle exige au moins 10 % du portefeuille en actions: inutile avec « FNB seulement ».",
        ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def _match_target(dimension: str, raw: str, allowed: dict[str, list[str]]) -> tuple[Optional[str], list[str]]:
    options = allowed.get(dimension, [])
    lookup = {o.lower(): o for o in options}
    key = raw.strip().lower()
    if key in lookup:
        return lookup[key], []
    return None, [lookup[m] for m in difflib.get_close_matches(key, list(lookup), n=3, cutoff=0.6)]


def validate_constraint(c: Constraint, allowed: dict[str, list[str]]) -> tuple[Optional[Constraint], Optional[str]]:
    """Retourne (contrainte normalisée, None) ou (None, message d'erreur en français)."""
    spec = SPECS[c.type]
    norm = c.model_copy(deep=True)

    if spec.dimension:
        if not c.target:
            return None, f"« {c.type.value} » exige une cible ({DIMENSION_FR[spec.dimension]})."
        if c.type in WILDCARD_TYPES and c.target.strip() == ANY:
            matched, suggestions = ANY, []
        elif c.type in SHARE_TYPES or c.type in MULTI_TARGET_TYPES:  # une région: pays absents ignorés
            found = [_match_target(spec.dimension, t, allowed) for t in share_targets(c)]
            matched = SEP.join(m for m, _ in found if m) or None
            suggestions = [s for _, more in found for s in more]
        else:
            matched, suggestions = _match_target(spec.dimension, c.target, allowed)
        if matched is None:
            hint = f" Vouliez-vous dire: {', '.join(suggestions)}?" if suggestions else ""
            return None, f"Le {DIMENSION_FR[spec.dimension]} « {c.target} » n'existe pas dans l'univers.{hint}"
        norm.target = matched
    else:
        norm.target = None

    if spec.kind == "none":
        norm.value = None
    elif c.value is None:
        return None, f"« {c.type.value} » exige une valeur."
    elif spec.kind == "count":
        if c.value < 1 or c.value != int(c.value):
            return None, f"« {c.type.value} » exige un entier supérieur ou égal à 1."
        norm.value = float(int(c.value))
    elif spec.kind == "score":
        if not -SCORE_RANGE <= c.value <= SCORE_RANGE:
            return None, f"« {c.type.value} » exige un score entre -3 et 3 écarts-types (ex.: 0.5)."
    elif c.type is T.MIN_EXPECTED_RETURN:
        if not -0.5 <= c.value <= 2:
            return None, "Le rendement minimal doit être une fraction réaliste (ex.: 0.06 pour 6 %)."
    elif not 0 <= c.value <= 1:
        return None, f"« {c.type.value} » exige une fraction entre 0 et 1 (ex.: 0.10 pour 10 %)."
    return norm, None


def validate_all(items: list[Constraint], allowed: dict[str, list[str]]) -> tuple[list[Constraint], list[str]]:
    valid, errors = [], []
    for c in items:
        norm, err = validate_constraint(c, allowed)
        if norm is not None:
            valid.append(norm)
        else:
            errors.append(err or "Contrainte invalide.")
    return valid, errors


# --------------------------------------------------------------------------- #
# Fusion et conflits
# --------------------------------------------------------------------------- #
def _key(c: Constraint | ConstraintRef) -> tuple[str, str]:
    return c.type.value, (c.target or "").lower()


def merge_constraints(
    existing: list[Constraint], incoming: list[Constraint], removals: list[ConstraintRef]
) -> list[Constraint]:
    """Une nouvelle contrainte remplace l'ancienne de même type et même cible. Les retraits sont appliqués."""
    removed = {_key(r) for r in removals}
    merged = {_key(c): c for c in existing if _key(c) not in removed}
    for c in incoming:
        merged[_key(c)] = c
    return list(merged.values())


def detect_conflicts(constraints: list[Constraint]) -> list[str]:
    """Conflits détectables sans optimisation. Seules les contraintes dures comptent.

    Complément (et non substitut) de `constraints.check_linear_feasibility`, qui tranche la faisabilité réelle par
    programmation linéaire une fois l'univers connu. Ici, aucun accès au marché: ces messages servent à poser une
    question au client avant toute construction.
    """
    hard = [c for c in constraints if c.hard]
    by = {_key(c): c for c in hard}
    out: list[str] = []

    def val(t: T, target: str = "") -> Optional[float]:
        c = by.get((t.value, target.lower()))
        return c.value if c else None

    for c in hard:
        spec = SPECS[c.type]
        if c.type is T.MIN_FACTOR_EXPOSURE and c.target:
            hi = val(T.MAX_FACTOR_EXPOSURE, c.target)
            if hi is not None and (c.value or 0) > hi + 1e-9:
                out.append(f"Conflit sur le facteur {c.target}: exposition minimale {c.value:+.2f} supérieure à "
                           f"l'exposition maximale {hi:+.2f}.")
        elif spec.direction == "min" and spec.dimension and c.target:
            twin = T(c.type.value.replace("min_", "max_"))
            hi = val(twin, c.target)
            if hi is not None and (c.value or 0) > hi + 1e-9:
                out.append(f"Conflit sur {c.target}: poids minimal {c.value:.0%} supérieur au poids maximal {hi:.0%}.")
            excl = T(f"exclude_{spec.dimension}")
            if (excl.value, c.target.lower()) in by and (c.value or 0) > 0:
                out.append(f"Conflit sur {c.target}: exclu, mais un poids minimal de {c.value:.0%} est demandé.")

    mn, mx = val(T.MIN_POSITIONS), val(T.MAX_POSITIONS)
    if mn is not None and mx is not None and mn > mx:
        out.append(f"Conflit: minimum de {mn:.0f} positions supérieur au maximum de {mx:.0f}.")
    cap = val(T.MAX_POSITION_WEIGHT)
    if cap is not None and mx is not None and cap * mx < 1 - 1e-9:
        out.append(
            f"Conflit: avec au plus {mx:.0f} positions de {cap:.0%} maximum, le portefeuille ne peut pas atteindre 100 %."
        )
    for dim in ("sector", "country", "asset_class"):
        total = sum((c.value or 0) for c in hard if c.type.value == f"min_{dim}_weight")
        if total > 1 + 1e-9:
            out.append(f"Conflit: la somme des poids minimaux par {DIMENSION_FR[dim]} dépasse 100 % ({total:.0%}).")
        shares = sum((c.value or 0) for c in hard if c.type.value == f"min_{dim}_share")
        if shares > 1 + 1e-9:
            out.append(f"Conflit: la somme des parts minimales par {DIMENSION_FR[dim]} dépasse 100 % ({shares:.0%}).")
    out += _exact_conflicts(hard)
    return out


def _exact_conflicts(hard: list[Constraint]) -> list[str]:
    """Pourcentages exacts contre exclusions, planchers, plafonds, et sommes de groupes disjoints."""
    out: list[str] = []
    exact = [c for c in hard if c.type in EXACT_TYPES and c.target]
    excluded = {(SPECS[c.type].dimension, t.lower()) for c in hard if SPECS[c.type].kind == "none" and c.target
                for t in share_targets(c)}
    bounds = {(SPECS[c.type].dimension, (c.target or "").lower(), SPECS[c.type].direction): c.value
              for c in hard if c.type in GROUP_TYPES and c.target and c.value is not None}
    for c in exact:
        dim, value = EXACT_TYPES[c.type], c.value or 0.0
        if value > 0 and any((dim, t.lower()) in excluded for t in share_targets(c)):
            out.append(f"Conflit sur {c.target}: exclu, mais exactement {value:.0%} est demandé.")
        low, high = bounds.get((dim, c.target.lower(), "min")), bounds.get((dim, c.target.lower(), "max"))
        if (low is not None and low > value + 1e-9) or (high is not None and high < value - 1e-9):
            out.append(f"Conflit sur {c.target}: exactement {value:.0%} demandé, hors de ses limites.")
        # Pays, secteur, thématique ne comptent que des actions détenues en direct, de classe Equity.
        no_stocks = ("instrument_type", "stock") in excluded or any(("asset_class", e) in excluded
                                                                   for e in EQUITY_CLASSES)
        if c.type in MULTI_TARGET_TYPES and value > 0 and no_stocks:
            out.append(f"Conflit sur {c.target}: {value:.0%} demandé en actions détenues en direct, mais les actions "
                       "sont exclues.")
    # Des groupes disjoints d'une même dimension ne peuvent pas dépasser 100 % ensemble. Les thématiques se
    # chevauchent (NVDA est ia et tech): jamais additionnées, comme deux dimensions différentes.
    for dim in ("asset_class", "instrument_type", "country", "sector"):
        groups = [c for c in exact if EXACT_TYPES[c.type] == dim]
        labels = [{t.lower() for t in share_targets(c)} for c in groups]
        total = sum(c.value or 0 for c in groups)
        if len(groups) > 1 and sum(map(len, labels)) == len(set().union(*labels)) and total > 1 + 1e-9:
            out.append(f"Conflit: les pourcentages exacts par {DIMENSION_FR[dim]} totalisent {total:.0%}.")
    return out


def share_targets(c: Constraint) -> list[str]:
    """Les libellés visés par une part (*_share)."""
    return [t.strip() for t in (c.target or "").split(SEP) if t.strip()]


def describe(c: Constraint) -> str:
    """Libellé lisible en français."""
    spec = SPECS[c.type]
    v = c.value
    pct = f"{v:.1%}".replace(".0%", "%") if v is not None else ""
    names = {
        T.MAX_POSITION_WEIGHT: f"Poids maximal par titre ≤ {pct}",
        T.MAX_STOCK_WEIGHT: f"Poids maximal par titre hors FNB ≤ {pct}",
        T.MIN_POSITIONS: f"Au moins {v:.0f} positions" if v else "",
        T.MAX_POSITIONS: f"Au plus {v:.0f} positions" if v else "",
        T.MAX_VOLATILITY: f"Volatilité annualisée ≤ {pct}",
        T.MIN_EXPECTED_RETURN: f"Rendement annualisé historique ≥ {pct}",
    }
    if c.type in names:
        label = names[c.type]
    elif c.type in SHARE_TYPES:
        sign = "≤" if spec.direction == "max" else "≥"
        label = f"Part de la poche actions, {DIMENSION_FR[spec.dimension]} {', '.join(share_targets(c))} {sign} {pct}"
    elif c.type in MULTI_TARGET_TYPES:
        label = (f"Part de la poche actions, {DIMENSION_FR[spec.dimension]} {', '.join(share_targets(c))} "
                 f"(actions détenues en direct) = {pct}")
    elif c.type in EXACT_TYPES:
        label = f"Poids {DIMENSION_FR[spec.dimension]} {', '.join(share_targets(c))} = {pct}"
    elif c.type in FACTOR_TYPES:
        sign = "≥" if spec.direction == "min" else "≤"
        name = factors.FACTOR_FR.get(c.target or "", c.target)
        label = f"Exposition {name} {sign} {v or 0:+.2f}".replace(".", ",")
    elif spec.kind == "none":
        label = f"Exclure {DIMENSION_FR[spec.dimension or 'symbol']}: {c.target}"
    else:
        sign = "≤" if spec.direction == "max" else "≥"
        dim = DIMENSION_FR[spec.dimension or "symbol"]
        subject = f"chaque {dim}" if c.target == ANY else f"{dim} {c.target}"
        label = f"Poids {subject} {sign} {pct}"
    return label + ("" if c.hard else " (préférence)")


# --------------------------------------------------------------------------- #
# Univers à la forme du moteur
# --------------------------------------------------------------------------- #
def is_fund(market: Market, symbol: str) -> bool:
    """Un FNB est diversifié par nature: `max_stock_weight` ne le plafonne pas."""
    return str(market.assets.loc[symbol].get("instrument_type", "")).lower() == "etf"


def is_stock(market: Market, symbol: str) -> bool:
    """Une action détenue en direct (ni FNB, ni crypto)."""
    return str(market.assets.loc[symbol].get("instrument_type", "")).lower() == "stock"


def is_equity(market: Market, symbol: str) -> bool:
    """La base des parts *_share: actions en direct et FNB d'actions."""
    return str(market.assets.loc[symbol].get("asset_class", "")).lower() in EQUITY_CLASSES


def in_share(market: Market, symbol: str, c: Constraint) -> bool:
    """Le titre est une action détenue en direct dont le secteur ou le pays fait partie des cibles de la part."""
    column = DIMENSION_COLUMN[SHARE_TYPES[c.type][0]]
    targets = {t.lower() for t in share_targets(c)}
    return is_stock(market, symbol) and str(market.assets.loc[symbol, column]).lower() in targets


def engine_universe(market: Market) -> pd.DataFrame:
    """`Market.assets` dans la forme attendue par `constraints.filter_eligible_universe`.

    `market.build_market` ne garde que les colonnes de métadonnées et les statistiques: `observations` et
    `is_included_universe` sont perdues en route. Or tout actif de `Market.assets` a déjà passé le filtre
    d'admissibilité et le minimum d'historique de `data.prepare_optimizer_data`, d'où `is_included_universe=True`.
    """
    u = market.assets.copy()
    u["observations"] = pd.to_numeric(u["n_obs"], errors="coerce").fillna(0).astype(int)
    u["is_included_universe"] = True
    return u


def _targets(market: Market, dimension: str, target: str) -> list[str]:
    """Les symboles dont la métadonnée correspond à la cible. Un FNB n'a ni secteur ni pays connu: il n'y figure pas."""
    a = market.assets
    if dimension == "symbol":
        return [s for s in a.index if s.lower() == target.lower()]
    column = DIMENSION_COLUMN[dimension]
    return a.index[a[column].astype(str).str.lower() == target.lower()].tolist()


def _groups_present(market: Market, dimension: str, symbols: Iterable[str]) -> list[str]:
    """Groupes réellement présents dans une sélection, hors « Non classé » (un FNB ne forme pas un secteur)."""
    column = DIMENSION_COLUMN[dimension]
    values = market.assets.loc[list(symbols), column].astype(str)
    return sorted({v for v in values if v != UNKNOWN})


# --------------------------------------------------------------------------- #
# Traduction vers le moteur
# --------------------------------------------------------------------------- #
def agent_request(
    market: Market,
    constraints: list[Constraint],
    *,
    risk_aversion: Optional[float] = None,
    hard_only: bool = True,
) -> dict[str, Any]:
    """Requête agent pour `config.get_agent_settings`, tirée des contraintes du client.

    Confié au moteur: exclusions (par classe d'actifs et par symbole), titres requis, plafond par actif, planchers et
    plafonds par classe d'actifs. Résolu en symboles: exclusions de secteur et de pays (voir l'en-tête du module).
    Hors du plan linéaire, donc laissé à l'optimiseur: volatilité maximale, rendement minimal, nombre de positions,
    `max_stock_weight` et `max_symbol_weight` (bornes appliquées par `plan_for`).
    """
    kept = [c for c in constraints if c.hard or not hard_only]
    excluded_symbols: set[str] = set()
    excluded_classes: set[str] = set()
    excluded_types: set[str] = set()
    preferences: dict[str, dict[str, dict[str, Any]]] = {}
    required: dict[str, float] = {}
    group_limits: dict[str, dict[str, dict[str, float]]] = {}
    cap: Optional[float] = None

    def prefer(dimension: str, group: str, mode: str, weight: Optional[float] = None) -> None:
        current = preferences.setdefault(dimension, {}).get(group)
        new = {"mode": mode, "weight": weight}
        if current is not None and current != new:
            raise ConstraintInfeasibleError(
                f"{DIMENSION_FR[dimension]} {group}: {current['mode']} et {mode} demandés en même temps.")
        preferences[dimension][group] = new

    for c in kept:
        spec = SPECS[c.type]
        if c.type is T.EXCLUDE_ASSET_CLASS and c.target:
            excluded_classes.add(c.target)
        elif c.type is T.EXCLUDE_INSTRUMENT_TYPE and c.target:
            excluded_types.add(c.target)
        elif c.type in STOCK_EXCLUSIONS and c.target:  # actions détenues en direct seulement
            for target in share_targets(c):
                prefer(STOCK_EXCLUSIONS[c.type], target, "exclude")
        elif c.type in EXACT_TYPES and c.target and c.value is not None:
            prefer(EXACT_TYPES[c.type], c.target, "exact", float(c.value))
        elif spec.kind == "none" and c.target:  # symbole
            excluded_symbols.update(_targets(market, spec.dimension or "symbol", c.target))
        elif c.type is T.MIN_SYMBOL_WEIGHT and c.target and c.value:
            for s in _targets(market, "symbol", c.target):
                required[s] = max(required.get(s, 0.0), float(c.value))
        elif c.type is T.MAX_POSITION_WEIGHT and c.value is not None:
            cap = float(c.value) if cap is None else min(cap, float(c.value))
        elif c.type in GROUP_TYPES and c.target and c.value is not None:
            dimension, direction = GROUP_TYPES[c.type]
            if dimension in ENGINE_DIMENSIONS and c.target != ANY:
                bounds = group_limits.setdefault(dimension, {}).setdefault(c.target, {})
                bounds[direction] = (
                    min(bounds.get(direction, 1.0), float(c.value)) if direction == "max"
                    else max(bounds.get(direction, 0.0), float(c.value))
                )

    aversion = risk_aversion if risk_aversion is not None else RISK_AVERSION["default"]
    request: dict[str, Any] = {
        "risk_aversion_A": float(min(max(aversion, RISK_AVERSION["min"]), RISK_AVERSION["max"])),
        "excluded_symbols": sorted(excluded_symbols),
        "excluded_asset_classes": sorted(excluded_classes),
    }
    # Question 1: les types exclus forment l'un des trois modes du moteur, sinon restent des exclusions de type.
    remaining = {t for t in INSTRUMENT_SELECTION["mixed"] if t.lower() not in {e.lower() for e in excluded_types}}
    mode = next((m for m, types in INSTRUMENT_SELECTION.items() if set(types) == remaining), None)
    request["instrument_selection"] = mode or "mixed"
    if mode is None and excluded_types:
        request["excluded_instrument_types"] = sorted(excluded_types)
    if preferences:
        request["preferences"] = preferences
    if cap is not None:
        request["max_weight_per_asset"] = cap
    if required:
        request["required_symbol_min_weights"] = required
    if group_limits:
        request["group_limits"] = group_limits
    return request


def settings_for(
    market: Market,
    constraints: list[Constraint],
    *,
    risk_aversion: Optional[float] = None,
    hard_only: bool = True,
) -> dict[str, Any]:
    """Réglages du moteur pour ces contraintes. Le cash synthétique est désactivé (absent du Parquet)."""
    settings = get_agent_settings(agent_request(market, constraints, risk_aversion=risk_aversion, hard_only=hard_only))
    settings["cash"]["enabled"] = False
    settings["constraints"]["min_cash_weight"] = 0.0
    return settings


def screen(
    market: Market,
    constraints: list[Constraint],
    *,
    risk_aversion: Optional[float] = None,
) -> ScreeningResult:
    """Univers admissible selon le moteur (`filter_eligible_universe`). Lève `ConstraintInfeasibleError` si vide."""
    settings = settings_for(market, constraints, risk_aversion=risk_aversion)
    return filter_eligible_universe(engine_universe(market), settings)


def excluded_mask(market: Market, constraints: list[Constraint], hard_only: bool = True) -> pd.Series:
    """Masque booléen (index = symbole) des actifs écartés, tel que le moteur les écarte.

    Ne lève pas: les outils des gestionnaires s'en servent pour décrire l'univers. Si le moteur ne laisse aucun
    actif, tout est marqué exclu et l'optimiseur rendra `invalid_selection` avec son propre message.
    """
    index = market.assets.index
    try:
        kept = screen(market, [c for c in constraints if c.hard or not hard_only]).symbols
        return pd.Series(~index.isin(kept), index=index)
    except (ConstraintError, ConstraintInfeasibleError) as exc:
        logger.info("Univers vide ou contraintes incompatibles: %s", exc)
        return pd.Series(True, index=index)


def _factor_groups(symbols: tuple[str, ...], items: list[Constraint]) -> list[GroupConstraint]:
    """Expositions aux facteurs en contraintes linéaires: b ≥ seuil ⟺ Σ wᵢ·(zᵢ − seuil) ≥ 0 sur les actions notées.

    Un FNB a un coefficient nul: sans plancher d'actions notées, un portefeuille 100 % FNB respecterait toute contrainte
    (0 ≥ 0). D'où `FACTOR_SLEEVE_MIN`. Les messages s'adressent au gestionnaire, qui peut corriger sa sélection.
    """
    if not items:
        return []
    scores = factors.scores_for(symbols)
    if scores.empty:
        raise ConstraintInfeasibleError(
            "Aucune action de la sélection n'a de score de facteur (les FNB n'en ont pas). Ajoute des actions "
            "détenues en direct: l'outil screen_factor donne les mieux notées.")
    position = {s: i for i, s in enumerate(symbols)}
    sleeve = np.zeros(len(symbols), dtype=float)
    for s in scores.index:
        sleeve[position[s]] = 1.0
    out = [GroupConstraint("factor:actions_notees", sleeve, FACTOR_SLEEVE_MIN, 1.0)]
    for c in items:
        factor, threshold = c.target or "", float(c.value or 0.0)
        if factor not in scores.columns:
            raise ConstraintError(f"Facteur inconnu: {factor!r}.")
        z = scores[factor]
        is_min = c.type is T.MIN_FACTOR_EXPOSURE
        target = threshold + FACTOR_MARGIN if is_min else threshold - FACTOR_MARGIN
        best = float(z.max() if is_min else z.min())
        if (is_min and best < target) or (not is_min and best > target):
            name = factors.FACTOR_FR.get(factor, factor)
            raise ConstraintInfeasibleError(
                f"L'action la mieux placée de la sélection a une exposition {name} de {best:+.2f}, alors que le "
                f"client demande {'au moins' if is_min else 'au plus'} {threshold:+.2f}. Ajoute des actions "
                f"{'mieux' if is_min else 'moins bien'} notées sur ce facteur (outil screen_factor).")
        coeff = np.zeros(len(symbols), dtype=float)
        for s, value in z.items():
            coeff[position[s]] = float(value) - target
        low, high = (0.0, np.inf) if is_min else (-np.inf, 0.0)
        out.append(GroupConstraint(f"factor:{factor}:{'min' if is_min else 'max'}", coeff, low, high))
    return out


def plan_for(
    market: Market,
    symbols: list[str],
    constraints: list[Constraint],
    *,
    risk_aversion: Optional[float] = None,
    verify: bool = True,
) -> ConstraintPlan:
    """Plan de contraintes du moteur pour une sélection, complété des limites que le moteur ne porte pas.

    Ajouts de ce module, dans le vocabulaire du moteur (`GroupConstraint`, bornes), donc toujours vérifiables par
    `constraints.validate_weights`:
    - plafonds et planchers par secteur et par pays, calculés sur les titres dont la métadonnée est connue;
    - cible « * » (chaque secteur, chaque pays) développée en une contrainte par groupe présent;
    - `max_stock_weight` (titres hors FNB) et `max_symbol_weight` en bornes supérieures.
    """
    settings = settings_for(market, constraints, risk_aversion=risk_aversion)
    universe = engine_universe(market).loc[list(dict.fromkeys(symbols))]
    plan = build_constraint_plan(universe, settings)

    kept = [c for c in constraints if c.hard]
    index = {s: i for i, s in enumerate(plan.symbols)}
    upper = plan.upper_bounds.copy()
    groups = list(plan.groups)

    def coefficients(dimension: str, group: str) -> np.ndarray:
        coeff = np.zeros(len(plan.symbols), dtype=float)
        for s in _targets(market, dimension, group):
            if s in index:
                coeff[index[s]] = 1.0
        return coeff

    for c in kept:
        if c.type is T.MAX_STOCK_WEIGHT and c.value is not None:
            for s, i in index.items():
                if not is_fund(market, s):
                    upper[i] = min(upper[i], float(c.value))
        elif c.type is T.MAX_SYMBOL_WEIGHT and c.target and c.value is not None:
            for s in _targets(market, "symbol", c.target):
                if s in index:
                    upper[index[s]] = min(upper[index[s]], float(c.value))
        elif c.type in SHARE_TYPES and c.target and c.value is not None:
            # Part p de la poche actions, linéaire: poids du groupe − p × poids de la poche ≥ 0 (min) ou ≤ 0 (max).
            coeff = np.zeros(len(plan.symbols), dtype=float)
            for s, i in index.items():
                coeff[i] = float(in_share(market, s, c)) - (float(c.value) if is_equity(market, s) else 0.0)
            low, high = (0.0, math.inf) if SHARE_TYPES[c.type][1] == "min" else (-math.inf, 0.0)
            groups.append(GroupConstraint(f"{c.type.value}:{c.target.casefold()}", coeff, low, high))
        elif c.type in GROUP_TYPES and c.target and c.value is not None:
            dimension, direction = GROUP_TYPES[c.type]
            if dimension in ENGINE_DIMENSIONS and c.target != ANY:
                continue  # déjà porté par `group_limits` du moteur
            targets = _groups_present(market, dimension, plan.symbols) if c.target == ANY else [c.target]
            for group in targets:
                coeff = coefficients(dimension, group)
                if not np.any(coeff > 0):
                    if direction == "min":
                        raise ConstraintInfeasibleError(
                            f"Aucun titre de la sélection n'est exposé à {DIMENSION_FR[dimension]} {group}."
                        )
                    continue
                low, high = (0.0, float(c.value)) if direction == "max" else (float(c.value), 1.0)
                groups.append(GroupConstraint(f"{dimension}:{group.casefold()}", coeff, low, high))

    groups += _factor_groups(plan.symbols, [c for c in kept if c.type in FACTOR_TYPES])

    if np.any(plan.lower_bounds > upper + 1e-12):
        bad = [plan.symbols[i] for i in np.flatnonzero(plan.lower_bounds > upper + 1e-12)]
        raise ConstraintInfeasibleError(f"Borne min supérieure à la borne max: {bad}")
    plan = dataclasses.replace(plan, upper_bounds=upper, groups=tuple(groups))
    if verify:
        check_linear_feasibility(plan)
    return plan


def audit(
    market: Market,
    weights: dict[str, float],
    constraints: list[Constraint],
    *,
    risk_aversion: Optional[float] = None,
) -> Optional[str]:
    """Vérification du moteur après résolution. Retourne None si tout passe, sinon son message.

    `constraints.validate_weights` est l'autorité sur le budget, les bornes, les groupes, les titres requis et le
    minimum de 1 %. `evaluate()` reste nécessaire par ailleurs: le juge et le frontend ont besoin du détail
    contrainte par contrainte, alors que cette fonction s'arrête au premier écart.
    """
    held = {s: w for s, w in weights.items() if w > HELD}
    if not held:
        return "Portefeuille vide."
    try:
        plan = plan_for(market, list(held), constraints, risk_aversion=risk_aversion, verify=False)
        validate_weights({s: held.get(s, 0.0) for s in plan.symbols}, plan)
    except (ConstraintError, ConstraintInfeasibleError) as exc:
        return str(exc)
    return None


# --------------------------------------------------------------------------- #
# Vérification contrainte par contrainte
# --------------------------------------------------------------------------- #
def evaluate(market: Market, weights: dict[str, float], constraints: list[Constraint]) -> list[ConstraintCheck]:
    """Vérifie un portefeuille contre toutes les contraintes (dures et préférences), sans jamais lever.

    Source de vérité de `JudgeVerdict.compliant` et des écarts montrés au client. Le détail par contrainte est
    calculé ici; `audit()` confronte en plus les poids au plan du moteur.
    """
    held = {s: w for s, w in weights.items() if w > HELD}
    metrics = None
    if held:
        try:
            metrics = market.portfolio_metrics(held)
        except ValueError as exc:  # historique commun insuffisant
            logger.info("Indicateurs indisponibles: %s", exc)
    a = market.assets
    checks: list[ConstraintCheck] = []

    def group_weight(dimension: str, target: str) -> float:
        t = target.lower()
        if dimension == "symbol":
            return sum(w for s, w in held.items() if s.lower() == t)
        col = DIMENSION_COLUMN[dimension]
        return sum(w for s, w in held.items() if str(a.loc[s, col]).lower() == t)

    def preference_weight(dimension: str, target: str) -> float:
        """Même coefficient que le moteur: pays, secteur et thématique ne comptent que les actions en direct."""
        return sum(w * preference_exposure(s, a.loc[s], dimension, target) for s, w in held.items())

    def max_group_weight(dimension: str) -> float:
        col = DIMENSION_COLUMN[dimension]
        sums: dict[str, float] = {}
        for s, w in held.items():
            key = str(a.loc[s, col])
            if key != UNKNOWN:  # les FNB et cryptos sans secteur ne forment pas un « secteur »
                sums[key] = sums.get(key, 0.0) + w
        return max(sums.values(), default=0.0)

    for c in constraints:
        spec = SPECS[c.type]
        v = c.value
        actual: Optional[float] = None
        passed = True

        if c.type is T.MAX_POSITION_WEIGHT:
            actual = max(held.values(), default=0.0)
            passed = actual <= (v or 0) + WTOL
        elif c.type is T.MAX_STOCK_WEIGHT:
            actual = max((w for s, w in held.items() if not is_fund(market, s)), default=0.0)
            passed = actual <= (v or 0) + WTOL
        elif c.type is T.MIN_POSITIONS:
            actual = float(len(held))
            passed = actual >= (v or 0)
        elif c.type is T.MAX_POSITIONS:
            actual = float(len(held))
            passed = actual <= (v or 0)
        elif c.type is T.MAX_VOLATILITY:
            actual = metrics.volatility if metrics else 0.0
            passed = actual <= (v or 0) + TOL
        elif c.type is T.MIN_EXPECTED_RETURN:
            actual = metrics.expected_return if metrics else 0.0
            passed = actual >= (v or 0) - TOL
        elif c.type in SHARE_TYPES:  # sans poche actions, la part ne s'applique pas
            equity = sum(w for s, w in held.items() if is_equity(market, s))
            if equity > HELD:
                actual = sum(w for s, w in held.items() if in_share(market, s, c)) / equity
                passed = actual <= (v or 0) + WTOL if spec.direction == "max" else actual >= (v or 0) - WTOL
        elif c.type in FACTOR_TYPES:
            actual, _ = factors.exposure(held, c.target or "")
            target = v or 0.0
            passed = actual is not None and (actual >= target - FTOL if spec.direction == "min"
                                             else actual <= target + FTOL)
        elif c.type in MULTI_TARGET_TYPES:  # part de la poche actions; sans poche actions, une part > 0 manque
            equity = sum(w for s, w in held.items() if is_equity(market, s))
            group = preference_weight(EXACT_TYPES[c.type], c.target or "")
            if equity > HELD:
                actual = group / equity
                passed = abs(actual - (v or 0.0)) <= EXACT_TOL / equity
            else:
                passed = (v or 0.0) <= EXACT_TOL and group <= HELD
        elif c.type in EXACT_TYPES:
            actual = preference_weight(EXACT_TYPES[c.type], c.target or "")
            passed = abs(actual - (v or 0.0)) <= EXACT_TOL
        elif c.type is T.EXCLUDE_THEME:
            actual = preference_weight("theme", c.target or "")
            passed = actual <= HELD
        elif spec.kind == "none":
            actual = group_weight(spec.dimension or "symbol", c.target or "")
            passed = actual <= HELD
        elif c.target == ANY:
            actual = max_group_weight(spec.dimension or "sector")
            passed = actual <= (v or 0) + WTOL
        else:
            actual = group_weight(spec.dimension or "symbol", c.target or "")
            passed = actual <= (v or 0) + WTOL if spec.direction == "max" else actual >= (v or 0) - WTOL

        fmt = {"count": lambda x: f"{x:.0f}", "score": lambda x: f"{x:+.2f}"}.get(spec.kind, lambda x: f"{x:.1%}")
        status = "respectée" if passed else "NON respectée"
        message = f"{status}: valeur observée {fmt(actual)}" if actual is not None else status
        if actual is None and c.type in FACTOR_TYPES:
            message += " (aucune action notée dans le portefeuille)"
        if v is not None and not passed:
            message += f", limite {fmt(v)}"
        checks.append(
            ConstraintCheck(
                constraint=c,
                label=describe(c),
                passed=passed,
                actual=None if actual is None else round(actual, 4),
                limit=v,
                message=message,
            )
        )
    return checks


__all__ = [
    "ANY", "DIMENSION_COLUMN", "DIMENSION_FR", "EXACT_TOL", "EXACT_TYPES", "HELD", "MULTI_TARGET_TYPES", "SEP",
    "SHARE_TYPES", "SPECS", "TOL", "WTOL", "Spec",
    "agent_request", "audit", "catalog_prompt", "describe", "detect_conflicts", "engine_universe",
    "evaluate", "excluded_mask", "in_share", "is_equity", "is_fund", "is_stock", "merge_constraints", "plan_for", "screen",
    "settings_for", "share_targets", "validate_all", "validate_constraint",
]
