"""Catalogue de contraintes, validation, fusion, détection de conflits et vérification.

Tout ce module est déterministe. Les agents proposent des contraintes; ce code décide de ce qui est
valide, de ce qui est fusionné et de ce qui est respecté.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Optional

from .data import Market
from .schemas import Constraint, ConstraintCheck, ConstraintRef, ConstraintType as T

TOL = 1e-3  # tolérance numérique sur la volatilité et le rendement
WTOL = 2e-4  # tolérance sur les poids (les poids sont arrondis à 4 décimales)
HELD = 5e-4  # poids à partir duquel une position est considérée comme détenue


@dataclass(frozen=True)
class Spec:
    dimension: Optional[str]  # sector | country | asset_class | region | theme | factor | instrument_type | symbol
    kind: str  # fraction | count | none
    direction: Optional[str]  # max | min | None
    description: str


SPECS: dict[T, Spec] = {
    T.MAX_POSITION_WEIGHT: Spec(None, "fraction", "max", "Poids maximal d'un titre (0.10 = 10 %)"),
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
    T.EXCLUDE_REGION: Spec("region", "none", None, "Exclure une région (actions et immobilier)"),
    T.MAX_REGION_WEIGHT: Spec("region", "fraction", "max", "Poids maximal d'une région"),
    T.MIN_REGION_WEIGHT: Spec("region", "fraction", "min", "Poids minimal d'une région"),
    T.EXCLUDE_THEME: Spec("theme", "none", None, "Exclure une thématique"),
    T.MAX_THEME_WEIGHT: Spec("theme", "fraction", "max", "Poids maximal d'une thématique"),
    T.MIN_THEME_WEIGHT: Spec("theme", "fraction", "min", "Poids minimal d'une thématique"),
    T.EXCLUDE_FACTOR: Spec("factor", "none", None, "Exclure un facteur (style)"),
    T.MAX_FACTOR_WEIGHT: Spec("factor", "fraction", "max", "Poids maximal d'un facteur"),
    T.MIN_FACTOR_WEIGHT: Spec("factor", "fraction", "min", "Poids minimal d'un facteur"),
    T.EXCLUDE_INSTRUMENT_TYPE: Spec("instrument_type", "none", None, "Exclure un type d'instrument (ex.: Stock)"),
    T.MAX_INSTRUMENT_LINE_WEIGHT: Spec("instrument_type", "fraction", "max",
                                       "Poids maximal de chaque ligne d'un type d'instrument (ex.: chaque Stock ≤ 10 %)"),
}

ANY = "*"  # cible générique: « chaque secteur » / « chaque pays » (plafonds seulement)
WILDCARD_TYPES = {T.MAX_SECTOR_WEIGHT, T.MAX_COUNTRY_WEIGHT}

WILDCARD_TYPES |= {T.MAX_REGION_WEIGHT}
DIMENSION_FR = {"sector": "secteur", "country": "pays", "asset_class": "classe d'actifs", "symbol": "titre",
                "region": "région", "theme": "thématique", "factor": "facteur", "instrument_type": "type d'instrument"}
ADDITIVE_DIMENSIONS = ("sector", "country", "asset_class", "region")  # groupes disjoints: les minimums s'additionnent


# --------------------------------------------------------------------------- #
# Catalogue présenté aux agents
# --------------------------------------------------------------------------- #
def catalog_prompt(allowed: dict[str, list[str]]) -> str:
    """Texte décrivant le catalogue de contraintes, pour le prompt de l'agent Extraction."""
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
        f"- region: {', '.join(allowed['region'])}",
        f"- theme: {', '.join(allowed['theme'])}",
        f"- factor: {', '.join(allowed['factor'])}",
        f"- instrument_type: {', '.join(allowed['instrument_type'])}",
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
    """Conflits détectables sans optimisation. Seules les contraintes dures comptent."""
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
    for dim in ADDITIVE_DIMENSIONS:
        total = sum((c.value or 0) for c in hard if c.type.value == f"min_{dim}_weight")
        if total > 1 + 1e-9:
            out.append(f"Conflit: la somme des poids minimaux par {DIMENSION_FR[dim]} dépasse 100 % ({total:.0%}).")
    return out


# --------------------------------------------------------------------------- #
# Univers admissible et vérification
# --------------------------------------------------------------------------- #
def excluded_mask(market: Market, constraints: list[Constraint], hard_only: bool = True):
    """Masque booléen (index = symbole) des actifs exclus par les contraintes."""
    mask = market.members("symbol", "\0")  # tout False
    for c in constraints:
        if hard_only and not c.hard:
            continue
        spec = SPECS[c.type]
        if spec.kind == "none" and spec.dimension:
            mask |= market.members(spec.dimension, c.target or "")
    return mask


def describe(c: Constraint) -> str:
    """Libellé lisible en français."""
    spec = SPECS[c.type]
    v = c.value
    pct = f"{v:.1%}".replace(".0%", "%") if v is not None else ""
    names = {
        T.MAX_POSITION_WEIGHT: f"Poids maximal par placement ≤ {pct}",
        T.MAX_INSTRUMENT_LINE_WEIGHT: f"Chaque ligne {c.target} ≤ {pct}",
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


def evaluate(market: Market, weights: dict[str, float], constraints: list[Constraint]) -> list[ConstraintCheck]:
    """Vérifie un portefeuille contre toutes les contraintes (dures et souples)."""
    held = {s: w for s, w in weights.items() if w > HELD}
    metrics = market.portfolio_metrics(held) if held else None
    checks: list[ConstraintCheck] = []

    def group_weight(dimension: str, target: str) -> float:
        inside = market.members(dimension, target)
        return sum(w for s, w in held.items() if bool(inside.get(s, False)))

    def max_group_weight(dimension: str) -> float:
        return max((group_weight(dimension, g) for g in market.groups(dimension)), default=0.0)

    for c in constraints:
        spec = SPECS[c.type]
        v = c.value
        actual: Optional[float] = None
        passed = True

        if c.type is T.MAX_POSITION_WEIGHT:
            actual = max(held.values(), default=0.0)
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
        elif c.type is T.MAX_INSTRUMENT_LINE_WEIGHT:
            inside = market.members("instrument_type", c.target or "")
            actual = max((w for s, w in held.items() if bool(inside.get(s, False))), default=0.0)
            passed = actual <= (v or 0) + WTOL
        elif spec.kind == "none":
            actual = group_weight(spec.dimension or "symbol", c.target or "")
            passed = actual <= HELD
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
