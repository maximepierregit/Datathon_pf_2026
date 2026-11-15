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
  Ce module résout donc « exclure le secteur Energy » en une liste de symboles (`excluded_symbols`), une dimension
  dont le moteur garantit l'exposition. Le contenu des FNB vient de `Market.exposures` (`etf_exposures.csv`): est
  exclu tout actif exposé à plus de `EXCLUSION_THRESHOLD` à la cible (les actions du secteur, VDY.TO et XIC.TO pour
  l'énergie, pas SPY à 4 %). Les plafonds et planchers par secteur ou par pays comptent chaque FNB au prorata.
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
from dataclasses import dataclass
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

from .config import RISK_AVERSION, get_agent_settings
from .constraints import (
    ConstraintError,
    ConstraintInfeasibleError,
    ConstraintPlan,
    GroupConstraint,
    ScreeningResult,
    build_constraint_plan,
    check_linear_feasibility,
    filter_eligible_universe,
    validate_weights,
)
from .market import UNKNOWN, Market
from .schemas import Constraint, ConstraintCheck, ConstraintRef, ConstraintType as T

logger = logging.getLogger(__name__)

TOL = 1e-3  # tolérance numérique sur la volatilité et le rendement
WTOL = 2e-4  # tolérance sur les poids (les poids sont arrondis à 4 décimales)
HELD = 5e-4  # poids à partir duquel une position est considérée comme détenue
# Exclure un secteur ou un pays écarte aussi tout FNB qui y place plus de 10 % de son capital (VDY.TO: 28 % d'énergie).
# Un FNB large reste admis (SPY: 4 % d'énergie): l'exposition résiduelle du portefeuille reste donc sous ce seuil.
EXCLUSION_THRESHOLD = 0.10
EXPOSED = ("sector", "country")  # dimensions comptées au prorata du contenu des FNB (Market.exposures)


# --------------------------------------------------------------------------- #
# Vocabulaire des agents
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Spec:
    dimension: Optional[str]  # sector | country | asset_class | symbol | None
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
    T.EXCLUDE_SYMBOL: Spec("symbol", "none", None, "Exclure un titre"),
    T.MAX_SECTOR_WEIGHT: Spec("sector", "fraction", "max", "Poids maximal d'un secteur"),
    T.MIN_SECTOR_WEIGHT: Spec("sector", "fraction", "min", "Poids minimal d'un secteur"),
    T.MAX_COUNTRY_WEIGHT: Spec("country", "fraction", "max", "Poids maximal d'un pays"),
    T.MIN_COUNTRY_WEIGHT: Spec("country", "fraction", "min", "Poids minimal d'un pays"),
    T.MAX_ASSET_CLASS_WEIGHT: Spec("asset_class", "fraction", "max", "Poids maximal d'une classe d'actifs"),
    T.MIN_ASSET_CLASS_WEIGHT: Spec("asset_class", "fraction", "min", "Poids minimal d'une classe d'actifs"),
    T.MAX_SYMBOL_WEIGHT: Spec("symbol", "fraction", "max", "Poids maximal d'un titre précis"),
    T.MIN_SYMBOL_WEIGHT: Spec("symbol", "fraction", "min", "Poids minimal d'un titre précis (le détenir)"),
}

ANY = "*"  # cible générique: « chaque secteur » / « chaque pays » (plafonds seulement)
WILDCARD_TYPES = {T.MAX_SECTOR_WEIGHT, T.MAX_COUNTRY_WEIGHT}

DIMENSION_COLUMN = {"sector": "sector", "country": "country", "asset_class": "asset_class", "symbol": None}
DIMENSION_FR = {"sector": "secteur", "country": "pays", "asset_class": "classe d'actifs", "symbol": "titre"}

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
        kind = {"fraction": " | valeur: fraction 0-1", "count": " | valeur: entier", "none": ""}[spec.kind]
        lines.append(f"- {t.value}: {spec.description}{target}{kind}")
    lines += [
        "",
        "Pour max_sector_weight et max_country_weight, la cible \"*\" signifie « chaque secteur » ou « chaque pays » "
        "(ex.: « pas plus de 25 % par secteur »). Pour un secteur ou un pays précis, utilise son libellé.",
        "",
        "VALEURS ACCEPTÉES POUR LES CIBLES (utiliser exactement ces libellés):",
        f"- sector: {', '.join(allowed['sector'])}",
        f"- country: {', '.join(allowed['country'])}",
        f"- asset_class: {', '.join(allowed['asset_class'])}",
        "- symbol: symbole boursier exact (utiliser l'outil search_universe pour retrouver un symbole à partir d'un nom)",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def _match_target(dimension: str, raw: str, allowed: dict[str, list[str]]) -> tuple[Optional[str], list[str]]:
    options = allowed[dimension]
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
        if spec.direction == "min" and spec.dimension and c.target:
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
    return out


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
    """Les symboles qu'une exclusion de cette cible écarte. Secteur et pays: tout actif exposé à plus de
    `EXCLUSION_THRESHOLD`, un FNB selon son contenu."""
    a = market.assets
    if dimension == "symbol":
        return [s for s in a.index if s.lower() == target.lower()]
    if dimension in EXPOSED:
        share = market.exposure_to(dimension, target)
        return share.index[share > EXCLUSION_THRESHOLD].tolist()
    column = DIMENSION_COLUMN[dimension]
    return a.index[a[column].astype(str).str.lower() == target.lower()].tolist()


def _share(market: Market, dimension: str, target: str) -> pd.Series:
    """Part du capital de chaque actif dans la cible: au prorata pour secteur et pays, 0 ou 1 sinon."""
    if dimension in EXPOSED:
        return market.exposure_to(dimension, target)
    a = market.assets
    if dimension == "symbol":
        return pd.Series((a.index.str.lower() == target.lower()).astype(float), index=a.index)
    return (a[DIMENSION_COLUMN[dimension]].astype(str).str.lower() == target.lower()).astype(float)


def _groups_present(market: Market, dimension: str, symbols: Iterable[str]) -> list[str]:
    """Groupes réellement présents dans une sélection (le contenu des FNB compris), hors « Non classé »."""
    symbols = list(symbols)
    if dimension in EXPOSED:
        e = market.exposures[dimension].loc[symbols]
        return sorted(str(c) for c in e.columns[e.sum() > 0])
    values = market.assets.loc[symbols, DIMENSION_COLUMN[dimension]].astype(str)
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
    required: dict[str, float] = {}
    group_limits: dict[str, dict[str, dict[str, float]]] = {}
    cap: Optional[float] = None

    for c in kept:
        spec = SPECS[c.type]
        if c.type is T.EXCLUDE_ASSET_CLASS and c.target:
            excluded_classes.add(c.target)
        elif spec.kind == "none" and c.target:  # secteur, pays, symbole
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
    - plafonds et planchers par secteur et par pays, chaque FNB au prorata de son contenu (`Market.exposures`);
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
        return _share(market, dimension, group).reindex(list(plan.symbols), fill_value=0.0).to_numpy(dtype=float)

    for c in kept:
        if c.type is T.MAX_STOCK_WEIGHT and c.value is not None:
            for s, i in index.items():
                if not is_fund(market, s):
                    upper[i] = min(upper[i], float(c.value))
        elif c.type is T.MAX_SYMBOL_WEIGHT and c.target and c.value is not None:
            for s in _targets(market, "symbol", c.target):
                if s in index:
                    upper[index[s]] = min(upper[index[s]], float(c.value))
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
        share = _share(market, dimension, target)
        return sum(w * float(share[s]) for s, w in held.items())

    def max_group_weight(dimension: str) -> float:
        if dimension in EXPOSED:
            return max(market.group_weights(dimension, held).values(), default=0.0) if held else 0.0
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
        elif spec.kind == "none":
            # Valeur observée: l'exposition du portefeuille (les FNB au prorata). Respectée si aucune position
            # n'est exclue par la contrainte (même règle que agent_request, seuil compris).
            actual = group_weight(spec.dimension or "symbol", c.target or "")
            banned = set(_targets(market, spec.dimension or "symbol", c.target or ""))
            passed = not any(s in banned for s in held)
        elif c.target == ANY:
            actual = max_group_weight(spec.dimension or "sector")
            passed = actual <= (v or 0) + WTOL
        else:
            actual = group_weight(spec.dimension or "symbol", c.target or "")
            passed = actual <= (v or 0) + WTOL if spec.direction == "max" else actual >= (v or 0) - WTOL

        is_count = spec.kind == "count"
        fmt = (lambda x: f"{x:.0f}") if is_count else (lambda x: f"{x:.1%}")
        status = "respectée" if passed else "NON respectée"
        message = f"{status}: valeur observée {fmt(actual)}" if actual is not None else status
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
    "ANY", "DIMENSION_COLUMN", "DIMENSION_FR", "EXCLUSION_THRESHOLD", "EXPOSED", "HELD", "SPECS", "TOL", "WTOL", "Spec",
    "agent_request", "audit", "catalog_prompt", "describe", "detect_conflicts", "engine_universe",
    "evaluate", "excluded_mask", "is_fund", "merge_constraints", "plan_for", "screen",
    "settings_for", "validate_all", "validate_constraint",
]
