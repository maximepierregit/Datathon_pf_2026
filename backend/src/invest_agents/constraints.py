from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .config import PREFERENCE_DIMENSIONS, PREFERENCE_LEVELS, validate_settings


# Les pays/secteurs de l'univers sont fiables uniquement pour les actions.
# Un ETF exige un look-through vérifié pour appliquer STRICTEMENT ces filtres.
ECONOMIC_DIMENSIONS = frozenset({"country", "region", "sector", "industry", "factor"})
EXCLUSIVE_EXPOSURE_DIMENSIONS = frozenset({"country", "region", "sector", "industry", "asset_class", "instrument_type"})
EXCLUSION_KEYS = {
    "asset_class": "excluded_asset_classes",
    "instrument_type": "excluded_instrument_types",
    "sector": "excluded_sectors",
    "country": "excluded_countries",
    "region": "excluded_regions",
    "theme": "excluded_themes",
    "factor": "excluded_factors",
}
UNKNOWN_LABELS = frozenset({"", "non classé", "non classe", "unknown", "n/a", "none", "nan", "<na>"})
TOL = 1e-9


class ConstraintError(ValueError):
    """Erreur dans un paramètre, une exposition ou les métadonnées."""


class ConstraintInfeasibleError(ConstraintError):
    """Restrictions incompatibles ou absence d'actifs admissibles."""


class UnresolvedPreferenceError(ConstraintError):
    """Une préférence souple ne peut pas encore être matérialisée."""


@dataclass(frozen=True)
class ScreeningResult:
    """Résultat d'un filtrage des titres, AVANT de calculer mu/Sigma."""

    universe: pd.DataFrame
    rejected: pd.DataFrame  # colonnes : symbol, reasons
    required_symbols: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(self.universe.index.astype(str))


@dataclass(frozen=True)
class CandidateSelection:
    """Sous-univers candidat ; ne préjuge PAS des titres effectivement détenus."""

    universe: pd.DataFrame
    symbols: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class GroupConstraint:
    """Une seule contrainte linéaire : minimum <= coefficient @ w <= maximum."""

    name: str
    coefficients: np.ndarray
    minimum: float = -math.inf
    maximum: float = math.inf


@dataclass(frozen=True)
class SoftPreference:
    """Instruction less/more, conservée sans pourcentage ni pénalité inventés."""

    dimension: str
    group: str
    level: str
    calibrated: bool


@dataclass(frozen=True)
class ConstraintPlan:
    """Contrat explicite à transmettre à optimizer.py après le filtrage."""

    symbols: tuple[str, ...]  # cash ajouté en dernier, si activé
    risky_symbols: tuple[str, ...]
    lower_bounds: np.ndarray
    upper_bounds: np.ndarray
    groups: tuple[GroupConstraint, ...]
    required_symbols: tuple[str, ...]
    minimum_held_weight: float
    cash_symbol: str | None
    sum_tolerance: float
    constraint_tolerance: float
    soft_preferences: tuple[SoftPreference, ...] = ()
    notices: tuple[str, ...] = ()

    def index_of(self, symbol: str) -> int:
        return self.symbols.index(str(symbol).strip().upper())


def _text(value: Any) -> str:
    """Ne jamais transformer NaN/pd.NA en faux groupe sectoriel."""
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    val = str(value).strip()
    return "" if val.casefold() in UNKNOWN_LABELS else val


def _key(value: Any) -> str:
    return _text(value).casefold()


def _ticker(value: Any) -> str:
    result = _text(value).upper()
    if not result:
        raise ConstraintError("Un ticker est vide ou invalide.")
    return result


def _number(value: Any, description: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ConstraintError(f"{description} : un booléen n'est pas un poids.")
    try:
        val = float(value)
    except (TypeError, ValueError) as exc:
        raise ConstraintError(f"{description} doit être un nombre fini.") from exc
    if not math.isfinite(val):
        raise ConstraintError(f"{description} doit être fini.")
    return val


def _fraction(value: Any, description: str) -> float:
    n = _number(value, description)
    if n < -TOL or n > 1 + TOL:
        raise ConstraintError(f"{description} : poids attendu dans [0, 1], reçu {n}.")
    return float(np.clip(n, 0.0, 1.0))


def _valid_settings(settings: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(settings, Mapping):
        raise ConstraintError("Passer explicitement get_base_settings() ou get_agent_settings(...).")
    validate_settings(settings)
    if settings.get("execution_mode") not in {"base", "agent"}:
        raise ConstraintError("Mode BASE/AGENT manquant. Utiliser get_settings(mode=...).")
    return settings


def _normalize_universe(universe: pd.DataFrame) -> pd.DataFrame:
    """Accepter l'index `symbol` issu de data.build_universe, ou une colonne."""
    if not isinstance(universe, pd.DataFrame) or universe.empty:
        raise ConstraintError("`universe` doit être un DataFrame non vide.")
    out = universe.copy()
    if "symbol" in out.columns:
        out = out.set_index("symbol", drop=True)
    if out.index.nlevels != 1:
        raise ConstraintError("L'univers doit avoir un seul niveau d'index symbol.")
    out.index = pd.Index([_ticker(s) for s in out.index], name="symbol")
    if not out.index.is_unique:
        raise ConstraintError("Chaque ticker doit figurer une seule fois dans l'univers.")
    for col in ("asset_class", "instrument_type", "observations", "is_included_universe"):
        if col not in out.columns:
            raise ConstraintError(f"Métadonnée obligatoire absente : {col!r}. Utiliser data.build_universe().")
    counts = pd.to_numeric(out["observations"], errors="coerce")
    if counts.isna().any() or (counts < 0).any():
        raise ConstraintError("`observations` doit contenir des comptes numériques >= 0.")
    if not out["is_included_universe"].dropna().isin([True, False, 0, 1]).all():
        raise ConstraintError("`is_included_universe` doit être booléen.")
    return out


def _override_fractions(
    symbol: str, dimension: str, overrides: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, float] | None:
    """Expositions manuelles EXPLICITES (jamais devinées dans les noms d'ETF)."""
    if not overrides or symbol not in overrides or dimension not in overrides[symbol]:
        return None
    raw = overrides[symbol][dimension]
    if not isinstance(raw, Mapping):
        raise ConstraintError(f"Look-through {symbol}/{dimension} doit être {{groupe: fraction}}.")
    result: dict[str, float] = {}
    for group, weight in raw.items():
        label = _text(group)
        if not label:
            raise ConstraintError(f"Groupe vide dans {symbol}/{dimension}.")
        k = _key(label)
        if k in result:
            raise ConstraintError(f"Groupe look-through dupliqué : {symbol}/{dimension}/{label}.")
        result[k] = _fraction(weight, f"Look-through {symbol}/{dimension}/{label}")
    if dimension in ECONOMIC_DIMENSIONS and not result:
        raise ConstraintError(
            f"Look-through vide pour {symbol}/{dimension} : couverture non démontrée.")
    if dimension in EXCLUSIVE_EXPOSURE_DIMENSIONS and sum(result.values()) > 1 + TOL:
        raise ConstraintError(f"Look-through {symbol}/{dimension} totalise plus de 100 %.")
    return result


def _exposure(
    symbol: str,
    row: pd.Series,
    dimension: str,
    overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[dict[str, float], bool]:
    """Retourne (fractions par groupe, couverture suffisamment complète).

    Une fraction sectorielle d'ETF (ex. 0,20) est utilisable pour une limite
    DE GROUPE, mais une couverture partielle ne garantit pas une exclusion de
    portefeuille complète. En mode strict on retire alors cet ETF.
    """
    manual = _override_fractions(symbol, dimension, overrides)
    if manual is not None:
        complete = (dimension not in EXCLUSIVE_EXPOSURE_DIMENSIONS or
                    sum(manual.values()) >= 1 - TOL)
        # Pour un facteur, la couverture ne peut être garantie sans la préciser ;
        # les valeurs manuelles restent le seul signal disponible.
        return manual, complete

    if dimension == "symbol":
        return {symbol.casefold(): 1.0}, True
    if dimension in {"asset_class", "instrument_type"}:
        val = _key(row.get(dimension))
        return ({val: 1.0}, True) if val else ({}, False)
    if dimension == "theme":
        raw = _text(row.get("theme"))
        tags = {_key(p) for p in raw.split(";") if _key(p)}
        # Couverture des TAGS publiée, pas look-through économique vérifié.
        return {tag: 1.0 for tag in tags}, True

    kind = _key(row.get("instrument_type"))
    if kind != "stock":
        # Dans universe.parquet, country/sector ETF = "Non classé".
        return {}, False
    if dimension in ECONOMIC_DIMENSIONS:
        value = _key(row.get(dimension))
        return ({value: 1.0}, True) if value else ({}, False)
    return {}, False


def _preferences(settings: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    raw = settings.get("agent_preferences", {})
    if not isinstance(raw, Mapping):
        raise ConstraintError("agent_preferences invalide.")
    out: dict[str, dict[str, str]] = {}
    for dimension, groups in raw.items():
        if dimension not in PREFERENCE_DIMENSIONS or not isinstance(groups, Mapping):
            raise ConstraintError(f"Préférences invalides : {dimension!r}.")
        out[dimension] = {}
        for group, level in groups.items():
            if _key(level) not in PREFERENCE_LEVELS:
                raise ConstraintError(f"Préférence {dimension}/{group} invalide.")
            out[dimension][_key(group)] = _key(level)
    return out


def _hard_exclusions(settings: Mapping[str, Any]) -> dict[str, set[str]]:
    c = settings["constraints"]
    out: dict[str, set[str]] = {}
    for dimension, fieldname in EXCLUSION_KEYS.items():
        out[dimension] = {_key(s) for s in c.get(fieldname, [])}
    out["symbol"] = {_key(s) for s in c.get("excluded_symbols", [])}
    for dimension, groups in _preferences(settings).items():
        out.setdefault(dimension, set()).update(g for g, level in groups.items() if level == "exclude")
    return out


def _required_symbols(settings: Mapping[str, Any]) -> tuple[str, ...]:
    c = settings["constraints"]
    required = {_ticker(s) for s in c["required_symbols"]}
    required.update(_ticker(s) for s in c["required_symbol_min_weights"])
    required.update(g.upper() for g, level in _preferences(settings).get("symbol", {}).items()
                    if level == "require")
    return tuple(sorted(required))


def _required_groups(settings: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    """Seuils d'une préférence require GROUPE, uniquement si explicites."""
    result: dict[str, dict[str, float]] = {}
    minimum = settings["preferences"]["require_group_min_weight"]
    for dimension, groups in _preferences(settings).items():
        if dimension == "symbol":
            continue
        for group, level in groups.items():
            if level == "require":
                if minimum is None:
                    raise ConstraintError(
                        f"Préférence require {dimension}/{group} : renseigner "
                        "preferences.require_group_min_weight dans config.py avant l'optimisation.")
                w = _fraction(minimum, "preferences.require_group_min_weight")
                if w <= 0:
                    raise ConstraintError("Une exigence de présence doit avoir un minimum strictement positif.")
                result.setdefault(dimension, {})[group] = w
    return result


def _controlled_economic_dimensions(settings: Mapping[str, Any]) -> set[str]:
    exclusions = _hard_exclusions(settings)
    group_limits = settings["constraints"]["group_limits"]
    required_groups = _required_groups(settings)
    return {
        d for d in ECONOMIC_DIMENSIONS
        if exclusions.get(d) or group_limits.get(d) or required_groups.get(d)
    }


def filter_eligible_universe(
    universe: pd.DataFrame,
    settings: Mapping[str, Any],
    *,
    exposure_overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> ScreeningResult:
    """Filtrer les exclusions STRICTES avant toute estimation de rendement/risque.

    Les instruments dont l'exposition est inconnue (secteur/pays/région/...) ne
    sont pas considérés à 0 % d'exposition : ils sont rejetés si une restriction
    économique sur cette dimension exige une garantie. Cela peut exclure des ETF
    tant qu'aucun fichier de look-through fiable n'est fourni.

    Le résultat préserve les colonnes originales, y compris `observations`.
    """
    cfg = _valid_settings(settings)
    meta = _normalize_universe(universe)
    c = cfg["constraints"]
    required = _required_symbols(cfg)
    exclusions = _hard_exclusions(cfg)
    economic_controls = _controlled_economic_dimensions(cfg)
    minimum_history = cfg["data"]["min_observations"]
    ineligible: dict[str, list[str]] = {}
    notes: list[str] = []

    if exposure_overrides:
        unknown_overrides = set(exposure_overrides) - set(meta.index)
        if unknown_overrides:
            raise ConstraintError(f"Look-through de symboles inconnus : {sorted(unknown_overrides)}")

    for symbol, row in meta.iterrows():
        reasons: list[str] = []
        included = row["is_included_universe"]
        if pd.isna(included) or not bool(included):
            reasons.append("not_in_investable_universe")
        if float(row["observations"]) < minimum_history:
            reasons.append(f"short_history:<{minimum_history}")
        instrument = _key(row.get("instrument_type"))
        if c["etf_only"] and instrument != "etf":
            reasons.append("etf_only")
        for dimension, groups in exclusions.items():
            if not groups:
                continue
            exposures, _ = _exposure(symbol, row, dimension, exposure_overrides)
            hits = sorted(g for g in groups if exposures.get(g, 0) > TOL)
            if hits:
                reasons.append(f"excluded_{dimension}:" + ",".join(hits))
        for dimension in economic_controls:
            _, complete = _exposure(symbol, row, dimension, exposure_overrides)
            if not complete:
                reasons.append(f"unknown_{dimension}_exposure")
        for dimension, groups in c["group_limits"].items():
            for group, bounds in groups.items():
                if "max" in bounds and bounds["max"] == 0:
                    exposed, _ = _exposure(symbol, row, dimension, exposure_overrides)
                    if exposed.get(_key(group), 0.0) > TOL:
                        reasons.append(f"zero_cap_{dimension}:{group}")
        if reasons:
            ineligible[symbol] = sorted(set(reasons))

    unknown_req = sorted(set(required) - set(meta.index))
    if unknown_req:
        raise ConstraintInfeasibleError(f"Titres requis absents de l'univers : {unknown_req}")
    blocked_req = {s: ineligible[s] for s in required if s in ineligible}
    if blocked_req:
        raise ConstraintInfeasibleError(f"Titres requis mais exclus/inadmissibles : {blocked_req}")

    chosen = meta.loc[~meta.index.isin(ineligible)].copy()
    if chosen.empty:
        raise ConstraintInfeasibleError("Aucun instrument admissible après filtrage strict.")
    for dimension, groups in _required_groups(cfg).items():
        for group in groups:
            if not any(_exposure(s, row, dimension, exposure_overrides)[0].get(group, 0) > TOL
                       for s, row in chosen.iterrows()):
                raise ConstraintInfeasibleError(f"Aucun instrument ne peut satisfaire require {dimension}/{group}.")

    rejects = pd.DataFrame([
        {"symbol": symbol, "reasons": tuple(reasons)}
        for symbol, reasons in sorted(ineligible.items())
    ], columns=["symbol", "reasons"])
    if economic_controls:
        notes.append("Expositions ETF inconnues : exclusion prudente pour les dimensions économiques contrôlées.")
    if exclusions.get("theme"):
        notes.append("Exclusion thématique fondée sur les tags du Parquet, sans garantie look-through des ETF.")
    return ScreeningResult(chosen.sort_index(), rejects, required, tuple(notes))


def _pairwise_duplicate(
    symbol: str, selected: Sequence[str], returns: pd.DataFrame, threshold: float,
    minimum_overlap: int,
) -> bool:
    """Décider si un candidat ressemble presque parfaitement à un candidat déjà retenu.

    Une corrélation n'est évaluée que sur des dates réellement communes, sans
    forward fill. Les instruments requis ne sont JAMAIS supprimés ici.
    """
    if symbol not in returns.columns:
        return False
    for other in selected:
        if other not in returns.columns:
            continue
        paired = returns[[symbol, other]].dropna()
        if len(paired) < minimum_overlap:
            continue
        if paired[symbol].std() <= TOL or paired[other].std() <= TOL:
            continue
        corr = paired[symbol].corr(paired[other])
        if pd.notna(corr) and corr >= threshold:
            return True
    return False


def select_candidates(
    screened: ScreeningResult,
    settings: Mapping[str, Any],
    *,
    returns: pd.DataFrame | None = None,
    exposure_overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> CandidateSelection:
    """Choisir ~50 candidats sans prédire les rendements ni optimiser les poids.

    Approche déterministe : garder les titres requis, couvrir les groupes avec
    un minimum explicite, puis répartir les choix entre les classes/instruments
    avec préférence aux historiques plus longs.

    La corrélation quasi-dupliquée ne peut être vérifiée QUE si une matrice de
    rendements historiques est fournie, déjà coupée à `as_of`.
    """
    cfg = _valid_settings(settings)
    if not isinstance(screened, ScreeningResult):
        raise ConstraintError("select_candidates exige d'abord ScreeningResult.")
    options = cfg["candidates"]
    all_meta = screened.universe
    required = list(screened.required_symbols)
    notices = list(screened.warnings)
    if not options["enabled"]:
        return CandidateSelection(all_meta.copy(), tuple(all_meta.index), tuple(notices))
    maximum = int(options["max_count"])
    target = min(int(options["target_count"]), maximum, len(all_meta))
    if len(required) > maximum:
        raise ConstraintInfeasibleError("Plus de titres requis que le maximum de candidats.")
    target = max(target, len(required))

    selected: list[str] = list(required)
    remaining = sorted(set(all_meta.index) - set(selected))
    need = _required_groups(cfg)
    for dimension, groups in need.items():
        for group in sorted(groups):
            already = any(_exposure(s, all_meta.loc[s], dimension, exposure_overrides)[0].get(group, 0) > TOL
                          for s in selected)
            if already:
                continue
            matches = [s for s in remaining
                       if _exposure(s, all_meta.loc[s], dimension, exposure_overrides)[0].get(group, 0) > TOL]
            if not matches:
                raise ConstraintInfeasibleError(f"Aucun candidat possible pour {dimension}/{group}.")
            matches.sort(key=lambda s: (-float(all_meta.loc[s, "observations"]), s))
            choice = matches[0]
            selected.append(choice)
            remaining.remove(choice)
    if len(selected) > maximum:
        raise ConstraintInfeasibleError("Les groupes obligatoires dépassent la capacité de présélection.")
    target = max(target, len(selected))

    # Score de diversification simple, sans anticipation de performance.
    count_by_dimension: dict[str, dict[str, int]] = {"asset_class": {}, "instrument_type": {}, "region": {}, "sector": {}}
    def bump(symbol: str) -> None:
        row = all_meta.loc[symbol]
        for dimension in count_by_dimension:
            label = _key(row.get(dimension))
            if label:
                count_by_dimension[dimension][label] = count_by_dimension[dimension].get(label, 0) + 1

    def candidate_score(symbol: str) -> tuple[float, float, str]:
        row = all_meta.loc[symbol]
        class_key = _key(row.get("asset_class"))
        type_key = _key(row.get("instrument_type"))
        region_key = _key(row.get("region"))
        sector_key = _key(row.get("sector"))
        novelty = (
            4.0 / (1 + count_by_dimension["asset_class"].get(class_key, 0))
            + 2.0 / (1 + count_by_dimension["instrument_type"].get(type_key, 0))
            + 1.0 / (1 + count_by_dimension["region"].get(region_key, 0))
            + 0.5 / (1 + count_by_dimension["sector"].get(sector_key, 0))
        )
        return (-novelty, -float(row["observations"]), symbol)

    for symbol in selected:
        bump(symbol)
    if returns is None and options["avoid_near_duplicate_exposures"]:
        notices.append("Corrélations quasi-dupliquées NON vérifiées (returns non fournis).")
    while remaining and len(selected) < target:
        remaining.sort(key=candidate_score)
        choice = remaining.pop(0)
        if (returns is not None and options["avoid_near_duplicate_exposures"]
                and _pairwise_duplicate(choice, selected, returns,
                                        float(options["near_duplicate_correlation_threshold"]),
                                        int(cfg["data"]["min_observations"]))):
            continue
        selected.append(choice)
        bump(choice)

    # Une liste de candidats doit être LINÉAIREMENT faisable, sans estimer mu/Sigma.
    # Si 50 actifs ne suffisent pas (ex. 80 % en actions avec cap de 10 %),
    # compléter au besoin jusqu'à max_count, sans perdre les titres requis.
    def verify_selection() -> None:
        p = build_constraint_plan(all_meta.loc[selected], cfg, exposure_overrides=exposure_overrides)
        check_linear_feasibility(p)

    try:
        verify_selection()
    except ConstraintInfeasibleError as first_error:
        expansion_pool = sorted(set(all_meta.index) - set(selected))
        while expansion_pool and len(selected) < maximum:
            expansion_pool.sort(key=candidate_score)
            choice = expansion_pool.pop(0)
            selected.append(choice)
            bump(choice)
            try:
                verify_selection()
                notices.append("Candidats supplémentaires ajoutés pour assurer la faisabilité linéaire.")
                break
            except ConstraintInfeasibleError:
                continue
        else:
            raise ConstraintInfeasibleError(
                f"Présélection impossible avec max_count={maximum} : {first_error}"
            ) from first_error

    if len(selected) < int(options["min_count"]):
        notices.append(f"Seulement {len(selected)} candidats disponibles ; min_count est une cible, pas une obligation.")
    if len(selected) < target:
        notices.append(f"Cible de {target} candidats non atteinte (filtre/déduplication).")
    result = all_meta.loc[selected].copy()
    return CandidateSelection(result, tuple(selected), tuple(notices))


def _group_specs(
    meta: pd.DataFrame,
    symbols: tuple[str, ...],
    settings: Mapping[str, Any],
    exposure_overrides: Mapping[str, Mapping[str, Any]] | None,
) -> list[GroupConstraint]:
    """Construire les coefficients linéaires de groupes, pouvant se chevaucher."""
    c = settings["constraints"]
    req_groups = _required_groups(settings)
    bounds_by_dimension: dict[str, dict[str, dict[str, float]]] = {}
    for dimension, groups in c["group_limits"].items():
        for group_name, bounds in groups.items():
            label = _key(group_name)
            normalized = bounds_by_dimension.setdefault(dimension, {}).setdefault(label, {})
            for k, v in bounds.items():
                normalized[k] = _fraction(v, f"group_limits.{dimension}.{group_name}.{k}")
    for dimension, groups in req_groups.items():
        for group_name, minimum in groups.items():
            bound = bounds_by_dimension.setdefault(dimension, {}).setdefault(group_name, {})
            bound["min"] = max(bound.get("min", 0), minimum)
    for dimension, param in (
        ("asset_class", "max_weight_by_asset_class"),
        ("instrument_type", "max_weight_by_instrument_type"),
    ):
        for group_name, ceiling in c[param].items():
            label = _key(group_name)
            bound = bounds_by_dimension.setdefault(dimension, {}).setdefault(label, {})
            bound["max"] = min(bound.get("max", 1.0), _fraction(ceiling, param + "." + group_name))

    linear: list[GroupConstraint] = []
    for dimension, groups in bounds_by_dimension.items():
        for group_name, bound in groups.items():
            low, high = bound.get("min", 0), bound.get("max", 1.0)
            if low > high + TOL:
                raise ConstraintInfeasibleError(f"Min > max : {dimension}/{group_name}.")
            coeff = np.zeros(len(symbols), dtype=float)
            for i, symbol in enumerate(symbols):
                if symbol not in meta.index:  # cash, pas d'exposition implicite
                    continue
                exposure, complete = _exposure(symbol, meta.loc[symbol], dimension, exposure_overrides)
                if dimension in ECONOMIC_DIMENSIONS and not complete:
                    raise ConstraintError(
                        f"Exposition non vérifiée : {symbol}/{dimension}. "
                        "Utiliser filter_eligible_universe ou ajouter un look-through vérifié.")
                coeff[i] = exposure.get(group_name, 0.0)
            if low > TOL and not np.any(coeff > TOL):
                raise ConstraintInfeasibleError(f"Aucun actif n'est exposé au groupe requis {dimension}/{group_name}.")
            linear.append(GroupConstraint(f"{dimension}:{group_name}", coeff, low, high))
    return linear


def build_constraint_plan(
    candidates: pd.DataFrame | CandidateSelection,
    settings: Mapping[str, Any],
    *,
    exposure_overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> ConstraintPlan:
    """Transformer les candidats en bornes et contraintes linéaires de poids.

    Ne calcule ni mu ni Sigma. `cash` est ajouté comme actif SYNTHÉTIQUE,
    absent de universe.parquet. Le cash n'a pas le minimum de 1 %.
    """
    cfg = _valid_settings(settings)
    if isinstance(candidates, CandidateSelection):
        meta = _normalize_universe(candidates.universe)
        notices = list(candidates.warnings)
    else:
        meta = _normalize_universe(candidates)
        notices = []
    risky = tuple(meta.index)
    cash = cfg["cash"]
    c = cfg["constraints"]
    cash_symbol = _ticker(cash["symbol"]) if cash["enabled"] else None
    if cash_symbol and cash_symbol in risky:
        raise ConstraintError("CASH-CAD synthétique est déjà présent dans l'univers.")
    symbols = risky + ((cash_symbol,) if cash_symbol else ())
    lower = np.zeros(len(symbols), dtype=float)
    upper = np.ones(len(symbols), dtype=float)
    min_held = _fraction(c["min_held_weight"], "min_held_weight")
    cap = c["max_weight_per_asset"]
    if cap is not None:
        upper[:len(risky)] = _fraction(cap, "max_weight_per_asset")
    required = _required_symbols(cfg)
    missing = sorted(set(required) - set(risky))
    if missing:
        raise ConstraintInfeasibleError(f"Titres obligatoires non sélectionnés : {missing}")
    for ticker in required:
        i = symbols.index(ticker)
        floor = c["required_symbol_min_weights"].get(ticker, min_held)
        lower[i] = max(lower[i], _fraction(floor, "required_symbol_min_weights." + ticker))
    if cash_symbol:
        lower[-1] = _fraction(c["min_cash_weight"], "min_cash_weight")
        upper[-1] = _fraction(c["max_cash_weight"], "max_cash_weight")
    elif c["min_cash_weight"] > TOL:
        raise ConstraintInfeasibleError("Cash désactivé avec un minimum de cash positif.")
    if np.any(lower > upper + TOL):
        bad = [symbols[i] for i in np.flatnonzero(lower > upper + TOL)]
        raise ConstraintInfeasibleError(f"Borne min supérieure à la borne max : {bad}")

    groups = _group_specs(meta, symbols, cfg, exposure_overrides)
    soft: list[SoftPreference] = []
    prefs = _preferences(cfg)
    pref_cfg = cfg["preferences"]
    for dimension, group_levels in prefs.items():
        for group, level in group_levels.items():
            if level in {"less", "more"}:
                calibrated = (
                    pref_cfg["soft_penalty_strength"] is not None
                    and pref_cfg["reference_allocation_source"] is not None
                    and pref_cfg[f"{level}_target_delta"] is not None
                )
                soft.append(SoftPreference(dimension, group, level, calibrated))
    if soft:
        notices.append("Les préférences less/more exigent une pénalisation calibrée dans optimizer.py.")
    return ConstraintPlan(
        symbols=symbols, risky_symbols=risky, lower_bounds=lower, upper_bounds=upper,
        groups=tuple(groups), required_symbols=required, minimum_held_weight=min_held,
        cash_symbol=cash_symbol, sum_tolerance=float(cfg["optimization"]["sum_weights_tolerance"]),
        constraint_tolerance=float(cfg["optimization"]["constraint_tolerance"]),
        soft_preferences=tuple(soft), notices=tuple(notices),
    )


def assert_ready_for_optimization(plan: ConstraintPlan) -> None:
    """Refuser une allocation qui ignorerait silencieusement less/more.

    Une future implémentation dans optimizer.py peut lever cette restriction
    APRÈS avoir réellement calculé les pénalités et les références.
    """
    unresolved = [f"{p.dimension}/{p.group}:{p.level}" for p in plan.soft_preferences]
    if unresolved:
        raise UnresolvedPreferenceError(
            "Préférences souples non intégrées à une fonction objectif calibrée : "
            + ", ".join(unresolved)
        )


def scipy_constraints(plan: ConstraintPlan) -> tuple[Any, tuple[Any, ...]]:
    """Sortie SciPy : Bounds + LinearConstraint (budget et groupes).

    ATTENTION : ceci ne représente PAS la disjonction `0 ou >= 1 %` ;
    optimizer.py devra exécuter prune/reoptimize et validate_weights.
    """
    from scipy.optimize import Bounds, LinearConstraint

    bounds = Bounds(plan.lower_bounds.copy(), plan.upper_bounds.copy())
    budget = LinearConstraint(np.ones(len(plan.symbols)), 1.0, 1.0)
    rest = tuple(LinearConstraint(g.coefficients, g.minimum, g.maximum) for g in plan.groups)
    return bounds, (budget,) + rest


def check_linear_feasibility(plan: ConstraintPlan) -> None:
    """Précontrôle de faisabilité LINÉAIRE par LP ; ne valide pas le minimum disjonctif."""
    from scipy.optimize import linprog

    upper_rows: list[np.ndarray] = []
    upper_rhs: list[float] = []
    for group in plan.groups:
        if math.isfinite(group.maximum):
            upper_rows.append(group.coefficients)
            upper_rhs.append(group.maximum)
        if math.isfinite(group.minimum):
            upper_rows.append(-group.coefficients)
            upper_rhs.append(-group.minimum)
    if float(plan.lower_bounds.sum()) > 1 + plan.sum_tolerance:
        raise ConstraintInfeasibleError("Somme des minima de pondération supérieure à 100 %.")
    if float(plan.upper_bounds.sum()) < 1 - plan.sum_tolerance:
        raise ConstraintInfeasibleError("Somme des maxima de pondération inférieure à 100 %.")
    result = linprog(
        c=np.zeros(len(plan.symbols)),
        A_ub=np.vstack(upper_rows) if upper_rows else None,
        b_ub=np.array(upper_rhs) if upper_rhs else None,
        A_eq=np.ones((1, len(plan.symbols))), b_eq=np.array([1.0]),
        bounds=list(zip(plan.lower_bounds.tolist(), plan.upper_bounds.tolist())),
        method="highs",
    )
    if not result.success:
        raise ConstraintInfeasibleError(f"Contraintes linéaires incompatibles : {result.message}")


def validate_weights(
    weights: Mapping[str, float] | Sequence[float] | np.ndarray,
    plan: ConstraintPlan,
    *,
    enforce_minimum_holding: bool = True,
) -> None:
    """Audit post-solve : budget, bornes, groupes, titres requis et minimum 1 %."""
    if isinstance(weights, Mapping):
        missing = set(plan.symbols) - set(weights)
        extra = set(weights) - set(plan.symbols)
        if missing or extra:
            raise ConstraintError(f"Poids : tickers manquants={sorted(missing)}, inconnus={sorted(extra)}")
        w = np.asarray([weights[s] for s in plan.symbols], dtype=float)
    else:
        w = np.asarray(weights, dtype=float)
    if w.ndim != 1 or len(w) != len(plan.symbols) or not np.all(np.isfinite(w)):
        raise ConstraintError("Vecteur de poids non fini ou de dimension incorrecte.")
    if abs(float(w.sum()) - 1.0) > plan.sum_tolerance:
        raise ConstraintInfeasibleError(f"Somme des poids = {w.sum():.9f} au lieu de 1.")
    tol = plan.constraint_tolerance
    for i, ticker in enumerate(plan.symbols):
        if w[i] < plan.lower_bounds[i] - tol or w[i] > plan.upper_bounds[i] + tol:
            raise ConstraintInfeasibleError(f"Poids {ticker} = {w[i]:.6f} hors bornes.")
    for group in plan.groups:
        exposure = float(group.coefficients @ w)
        if exposure < group.minimum - tol or exposure > group.maximum + tol:
            raise ConstraintInfeasibleError(f"Groupe {group.name} : poids {exposure:.6f} hors limites.")
    if enforce_minimum_holding:
        for i, ticker in enumerate(plan.risky_symbols):
            if tol < w[i] < plan.minimum_held_weight - tol:
                raise ConstraintInfeasibleError(f"{ticker} détenu à {w[i]:.4%}, sous le minimum de 1 %.")


def summarize_plan(plan: ConstraintPlan) -> dict[str, Any]:
    """Résumé JSON-compatible destiné à Kiro, aux tests et à l'explication du jury."""
    return {
        "risky_assets": len(plan.risky_symbols),
        "total_symbols_including_cash": len(plan.symbols),
        "required_symbols": list(plan.required_symbols),
        "min_held_weight": plan.minimum_held_weight,
        "cash_symbol": plan.cash_symbol,
        "group_constraints": [
            {"name": g.name, "minimum": g.minimum, "maximum": g.maximum,
             "affected_assets": int((g.coefficients > TOL).sum())}
            for g in plan.groups
        ],
        "soft_preferences": [
            {"dimension": p.dimension, "group": p.group, "level": p.level,
             "calibrated": p.calibrated}
            for p in plan.soft_preferences
        ],
        "notices": list(plan.notices),
        "minimum_holding_requires_post_processing": True,
    }


__all__ = [
    "CandidateSelection", "ConstraintError", "ConstraintInfeasibleError",
    "ConstraintPlan", "GroupConstraint", "ScreeningResult", "SoftPreference",
    "UnresolvedPreferenceError", "assert_ready_for_optimization",
    "build_constraint_plan", "check_linear_feasibility", "filter_eligible_universe",
    "scipy_constraints", "select_candidates", "summarize_plan", "validate_weights",
]
