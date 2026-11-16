"""Optimisation vue par les agents: un résultat lisible et corrigeable, au-dessus du solveur de `optimizer.py`.

`optimizer.optimize_weights` est l'autorité numérique: résolution continue, règle « 0 ou au moins 1 % »
(prune/reoptimize) et audit strict par `constraints.validate_weights`. Il lève une exception au premier obstacle,
ce qui convient à un script mais pas à un gestionnaire: l'agent doit lire un statut, comprendre pourquoi sa
sélection ne passe pas et la corriger. Ce module fait la traduction dans les deux sens.

DEUX ÉCARTS À CONNAÎTRE
- **Un seul objectif existe côté moteur**: l'utilité moyenne-variance `U = mu - A/2 var`. Les mandats historiques
  (`min_volatility`, `max_sharpe`, `max_return`) sont obtenus en déplaçant A le long de la frontière efficiente:
  A élevé pour la volatilité minimale, A faible pour le rendement maximal, et un balayage de A pour le meilleur
  ratio de Sharpe. MonPort, lui, passe déjà par `mean_variance` avec le A calculé par `monport.risk_aversion`.
- **Le plafond de volatilité n'est pas une contrainte linéaire**, donc le plan du moteur ne peut pas le porter.
  Il est obtenu en augmentant A jusqu'à ce que la volatilité passe sous le plafond, puis affiné par dichotomie
  pour ne pas sacrifier de rendement. `catalog.evaluate` tranche en dernier: un portefeuille qui dépasse encore
  le plafond est rendu `infeasible`, jamais présenté comme valide.

Le nombre de positions (`min_positions`, `max_positions`) reste gouverné par la taille de la sélection: le moteur
n'a pas de contrainte de cardinalité. Une sélection hors bornes est refusée ici, avant toute résolution, avec un
message qui dit au gestionnaire quoi changer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal, Optional

import numpy as np
import pandas as pd

from . import catalog
from .catalog import evaluate, excluded_mask
from .constraints import ConstraintError, ConstraintInfeasibleError, ConstraintPlan
from .market import Market
from .optimizer import EstimationError, OptimizationError, PortfolioResult, optimize_weights
from .runtime import get_runtime_settings
from .schemas import Constraint, ConstraintCheck, ConstraintType as T, PortfolioMetrics

logger = logging.getLogger(__name__)

Objective = Literal["min_volatility", "max_sharpe", "max_return", "mean_variance"]

MIN_POSITION_WEIGHT = 0.01  # « 0 ou au moins 1 % », appliqué par le moteur
A_MIN, A_MAX = 1.0, 25.0  # bornes de l'aversion au risque dans config.RISK_AVERSION
# Échelle de A parcourue pour `max_sharpe` et pour atteindre un plafond de volatilité.
A_LADDER = (1.0, 1.5, 2.0, 3.0, 4.5, 7.0, 10.0, 14.0, 18.0, 25.0)
CAP_REFINEMENTS = 6  # pas de dichotomie pour coller au plafond sans le dépasser


@dataclass
class OptimizationResult:
    status: Literal["optimal", "feasible", "infeasible", "invalid_selection"]
    message: str
    weights: dict[str, float] = field(default_factory=dict)
    metrics: Optional[PortfolioMetrics] = None
    failed_checks: list[ConstraintCheck] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)  # traçabilité du Markowitz global (`optimize_universe`)

    @property
    def ok(self) -> bool:
        return self.status in ("optimal", "feasible")


# --------------------------------------------------------------------------- #
# Sélection
# --------------------------------------------------------------------------- #
def _check_selection(
    market: Market, symbols: list[str], constraints: list[Constraint]
) -> tuple[list[str], Optional[str]]:
    """Normalise la sélection du gestionnaire. Retourne (symboles, message d'erreur à lui transmettre)."""
    picked = list(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip()))
    if not picked:
        return [], "Aucun symbole fourni."
    unknown = [s for s in picked if s not in market.assets.index]
    if unknown:
        return [], f"Symboles inconnus dans l'univers: {', '.join(sorted(unknown))}."

    hard = [c for c in constraints if c.hard]
    excluded = market.assets.index[excluded_mask(market, hard)]
    forbidden = [s for s in picked if s in excluded]
    if forbidden:
        return [], (f"Ces titres sont écartés par les contraintes: {', '.join(sorted(forbidden))}. "
                    "Choisis-en d'autres dans l'univers admissible.")

    settings = get_runtime_settings()
    ceiling = min([settings.max_assets_per_portfolio]
                  + [int(c.value) for c in hard if c.type is T.MAX_POSITIONS and c.value])
    floor = max([0] + [int(c.value) for c in hard if c.type is T.MIN_POSITIONS and c.value])
    if len(picked) > ceiling:
        return [], f"{len(picked)} titres sélectionnés, maximum {ceiling}. Retire des titres."
    if len(picked) < floor:
        return [], f"{len(picked)} titres sélectionnés, minimum {floor}. Ajoute des titres."
    return picked, None


# --------------------------------------------------------------------------- #
# Résolution
# --------------------------------------------------------------------------- #
def _volatility_cap(constraints: list[Constraint], vol_cap: Optional[float]) -> Optional[float]:
    """Le plafond le plus strict entre celui du mandat et ceux du client."""
    caps = [c.value for c in constraints if c.hard and c.type is T.MAX_VOLATILITY and c.value]
    if vol_cap is not None:
        caps.append(float(vol_cap))
    return min(caps) if caps else None


def _solve(
    market: Market, plan: ConstraintPlan, settings: dict, mu: pd.Series, sigma: pd.DataFrame, aversion: float
) -> PortfolioResult:
    settings["risk_aversion"]["default"] = float(min(max(aversion, A_MIN), A_MAX))
    return optimize_weights(mu, sigma, plan, settings)


def _best_sharpe(
    market: Market, plan: ConstraintPlan, settings: dict, mu: pd.Series, sigma: pd.DataFrame
) -> tuple[Optional[PortfolioResult], Optional[float]]:
    """Portefeuille tangent approché: le meilleur ratio de Sharpe le long de l'échelle de A."""
    rf, best, best_a, best_sharpe = market.risk_free_rate, None, None, -np.inf
    for a in A_LADDER:
        try:
            run = _solve(market, plan, settings, mu, sigma, a)
        except (ConstraintInfeasibleError, OptimizationError, ConstraintError):
            continue
        if run.volatility_annual <= 0:
            continue
        sharpe = (run.expected_return_annual - rf) / run.volatility_annual
        if sharpe > best_sharpe:
            best, best_a, best_sharpe = run, a, sharpe
    return best, best_a


def _under_cap(
    market: Market, plan: ConstraintPlan, settings: dict, mu: pd.Series, sigma: pd.DataFrame,
    run: PortfolioResult, aversion: float, cap: float,
) -> tuple[PortfolioResult, float]:
    """Monte A jusqu'à passer sous le plafond de volatilité, puis affine pour garder le plus de rendement."""
    if run.volatility_annual <= cap:
        return run, aversion
    low = aversion  # dépasse le plafond
    high: Optional[float] = None
    best = run
    for a in [x for x in A_LADDER if x > aversion] + [A_MAX]:
        try:
            trial = _solve(market, plan, settings, mu, sigma, a)
        except (ConstraintInfeasibleError, OptimizationError, ConstraintError):
            continue
        if trial.volatility_annual <= cap:
            high, best = a, trial
            break
        low = a
    if high is None:
        return best, low  # même A = 25 ne suffit pas: `evaluate` rendra le résultat infeasible
    for _ in range(CAP_REFINEMENTS):  # dichotomie: coller au plafond par le dessous
        middle = (low + high) / 2
        try:
            trial = _solve(market, plan, settings, mu, sigma, middle)
        except (ConstraintInfeasibleError, OptimizationError, ConstraintError):
            break
        if trial.volatility_annual <= cap:
            high, best = middle, trial
        else:
            low = middle
    return best, high


def _weights(run: PortfolioResult) -> dict[str, float]:
    """Poids arrondis à 4 décimales, résidu replacé sur la position la plus lourde (somme exactement 1)."""
    raw = {str(s): float(w) for s, w in run.weights.items() if float(w) > MIN_POSITION_WEIGHT / 2}
    if not raw:
        return {}
    out = {s: round(w, 4) for s, w in sorted(raw.items(), key=lambda kv: -kv[1])}
    residual = round(1.0 - sum(out.values()), 4)
    if residual:
        first = next(iter(out))
        out[first] = round(out[first] + residual, 4)
    return out


# --------------------------------------------------------------------------- #
# Point d'entrée des agents
# --------------------------------------------------------------------------- #
def optimize(
    market: Market,
    symbols: list[str],
    objective: Objective,
    constraints: list[Constraint],
    *,
    vol_cap: Optional[float] = None,
    risk_aversion: Optional[float] = None,
) -> OptimizationResult:
    """Optimise les poids d'une sélection, sans jamais lever: le gestionnaire lit le statut et corrige.

    `vol_cap` est le plafond de volatilité du mandat; il s'ajoute à ceux du client, le plus strict gagne.
    `risk_aversion` est le coefficient A de `mean_variance` (1 très audacieux … 25 très prudent).
    """
    picked, error = _check_selection(market, symbols, constraints)
    if error:
        return OptimizationResult("invalid_selection", error)
    if objective == "mean_variance" and risk_aversion is None:
        raise ValueError("L'objectif mean_variance exige un coefficient d'aversion au risque.")

    cap = _volatility_cap(constraints, vol_cap)
    try:
        plan = catalog.plan_for(market, picked, constraints, risk_aversion=risk_aversion, verify=True)
        settings = catalog.settings_for(market, constraints, risk_aversion=risk_aversion)
        risky = list(plan.risky_symbols)
        raw_mu, raw_cov = market.moments(risky)
        mu = pd.Series(raw_mu, index=risky, dtype=float)
        sigma = pd.DataFrame(raw_cov, index=risky, columns=risky, dtype=float)
    except (ConstraintInfeasibleError, ConstraintError, EstimationError, OptimizationError) as exc:
        return OptimizationResult("infeasible", str(exc))
    except ValueError as exc:  # historique commun insuffisant (Market.moments)
        return OptimizationResult("invalid_selection", str(exc))

    aversion = {"min_volatility": A_MAX, "max_return": A_MIN}.get(objective, risk_aversion or A_MAX / 2)
    try:
        if objective == "max_sharpe":
            run, found = _best_sharpe(market, plan, settings, mu, sigma)
            if run is None:
                return OptimizationResult("infeasible", "Aucune pondération ne respecte les contraintes.")
            aversion = found or aversion
        else:
            run = _solve(market, plan, settings, mu, sigma, aversion)
        if cap is not None:
            run, aversion = _under_cap(market, plan, settings, mu, sigma, run, aversion, cap)
    except ConstraintInfeasibleError as exc:
        return OptimizationResult("infeasible", str(exc))
    except (OptimizationError, ConstraintError) as exc:
        return OptimizationResult("infeasible", f"Optimisation impossible: {exc}")

    weights = _weights(run)
    if not weights:
        return OptimizationResult("infeasible", "L'optimiseur n'a retenu aucune position.")
    try:
        metrics = market.portfolio_metrics(weights)
    except ValueError as exc:
        return OptimizationResult("invalid_selection", str(exc))

    # Revérification: les chiffres montrés au client sont ceux de `catalog.evaluate`, pas ceux du solveur.
    checks = evaluate(market, weights, [c for c in constraints if c.hard])
    failed = [c for c in checks if not c.passed]
    if failed:
        return OptimizationResult(
            "infeasible",
            "Contraintes non respectées: " + "; ".join(f"{c.label} ({c.message})" for c in failed[:4]),
            weights=weights, metrics=metrics, failed_checks=failed,
        )
    status = "feasible" if run.notices else "optimal"
    message = f"Optimisé avec une aversion au risque A = {aversion:g}."
    if audit := catalog.audit(market, weights, constraints, risk_aversion=risk_aversion):
        logger.info("Audit du moteur après arrondi: %s", audit)
        status, message = "feasible", f"{message} Écart d'arrondi signalé par le moteur: {audit}"
    return OptimizationResult(status, message, weights=weights, metrics=metrics)


# --------------------------------------------------------------------------- #
# Markowitz global: tous les titres admissibles, puis 25 à 60 positions détenues (cible 50)
# --------------------------------------------------------------------------- #
POSITIVE = 1e-6  # poids considéré comme positif dans la solution continue


def universe_symbols(market: Market, constraints: list[Constraint]) -> tuple[list[str], dict]:
    """Filtre 1 (questionnaire: seuls les titres réellement interdits) puis filtre 2 (historique depuis 2021).

    Les contraintes de pondération (30 % d'obligations, 45 % de technologie…) ne retirent aucun titre: elles restent
    des contraintes de Markowitz.
    """
    hard = [c for c in constraints if c.hard]
    admissible = market.assets.index[~excluded_mask(market, hard)].tolist()
    history = market.history()
    long_enough = set(history.eligible)
    kept = [s for s in admissible if s in long_enough]
    short = [s for s in admissible if s not in long_enough]
    return kept, {
        "initial_universe": int(len(market.assets)),
        "eligible_after_questionnaire": len(admissible),
        "excluded_by_questionnaire": sorted(set(market.assets.index) - set(admissible)),
        "excluded_for_short_history": short,
        "eligible_after_history_filter": len(kept),
    }


def restrict_plan(plan: ConstraintPlan, keep: list[int], floor: float) -> ConstraintPlan:
    """Le plan réduit aux positions retenues: chaque position risquée détenue pèse au moins `floor`."""
    import dataclasses

    from .constraints import GroupConstraint

    risky_n = len(plan.risky_symbols)
    index = sorted(set(keep) | ({risky_n} if plan.cash_symbol else set()))
    symbols = tuple(plan.symbols[i] for i in index)
    lower = np.array([plan.lower_bounds[i] if i >= risky_n else max(plan.lower_bounds[i], floor) for i in index])
    upper = np.array([plan.upper_bounds[i] for i in index])
    groups = tuple(GroupConstraint(g.name, g.coefficients[index], g.minimum, g.maximum) for g in plan.groups)
    return dataclasses.replace(
        plan, symbols=symbols, risky_symbols=tuple(s for s in symbols if s != plan.cash_symbol),
        lower_bounds=lower, upper_bounds=upper, groups=groups,
        required_symbols=tuple(s for s in plan.required_symbols if s in symbols))


def _continuous(plan: ConstraintPlan, settings: dict, mu: np.ndarray, sigma: np.ndarray, aversion: float) -> np.ndarray:
    """Optimum continu de Markowitz (avant la règle 0 ou >= 1 %), avec le solveur du moteur."""
    from .optimizer import _linear_lp, _solve_slsqp

    if plan.cash_symbol:  # cash synthétique: rendement de config, variance et covariances nulles
        mu = np.append(mu, float(settings["cash"]["annual_expected_return"]))
        sigma = np.pad(sigma, ((0, 1), (0, 1)))
    low, high = plan.lower_bounds.copy(), plan.upper_bounds.copy()
    start = _linear_lp(plan, low, high)
    if start is None:
        raise ConstraintInfeasibleError("Budget, groupes et bornes: problème linéaire impossible sur l'univers.")
    w, _, _ = _solve_slsqp(mu, sigma, aversion, plan, settings, low, high, start)
    return w


def _feasible(plan: ConstraintPlan, keep: list[int], floor: float) -> bool:
    from .optimizer import _linear_lp

    sub = restrict_plan(plan, keep, floor)
    return _linear_lp(sub, sub.lower_bounds, sub.upper_bounds) is not None


def _floored(plan: ConstraintPlan, settings: dict, mu: np.ndarray, sigma: np.ndarray, aversion: float,
             keep: list[int]) -> Optional[tuple[float, np.ndarray]]:
    """Utilité et poids (vecteur complet) de l'optimum sur `keep`, chaque position à au moins 1 %; None si infaisable."""
    idx = sorted(keep)
    sub = restrict_plan(plan, idx, float(plan.minimum_held_weight))
    try:
        sub_w = _continuous(sub, settings, mu[idx], sigma[np.ix_(idx, idx)], aversion)
    except (ConstraintInfeasibleError, OptimizationError):
        return None
    x = sub_w[: len(idx)]
    w = np.zeros(len(plan.symbols))
    w[idx] = x
    return _utility(x, mu[idx], sigma[np.ix_(idx, idx)], aversion, settings), w


def _utility(w: np.ndarray, mu: np.ndarray, sigma: np.ndarray, aversion: float, settings: dict) -> float:
    """L'utilité que maximise l'optimiseur, pénalités de config.REGULARIZATION comprises."""
    from .optimizer import regularization_coefficients, regularization_penalty

    lambda_d, lambda_v, threshold = regularization_coefficients(settings)
    return float(w @ mu - 0.5 * aversion * w @ sigma @ w - regularization_penalty(w, sigma, lambda_d, lambda_v, threshold))


def select_holdings(plan: ConstraintPlan, settings: dict, mu: np.ndarray, sigma: np.ndarray, aversion: float,
                    w0: np.ndarray, holdings: dict) -> tuple[list[int], dict]:
    """Choisit les positions détenues dans la plage [min_count, max_count], à partir de l'optimum continu global.

    Aucune cible fixe: le nombre final dépend de A, des rendements, des covariances et des contraintes.
    Heuristique, sans garantie d'optimum global (cardinalité et « 0 ou >= 1 % » ne sont pas convexes):
    1. part des titres que Markowitz détient (plus gros poids d'abord, au plus `max_count`);
    2. complète jusqu'à `min_count` avec les titres d'utilité marginale mu_i − A·(Sigma·w)_i la plus élevée: ce terme
       tient compte de la covariance avec le portefeuille courant (un titre peu corrélé y gagne même avec un
       rendement modeste);
    3. garantit un titre à chaque groupe imposé (pourcentage exact, présence d'une action);
    4. continue d'ajouter par lots de 5 tant que chaque position ajoutée coûte au plus `max_marginal_utility_cost`
       d'utilité (positions toutes à >= 1 %), sans dépasser `max_count`.
    Cas extrêmes: si l'univers est plus petit que `min_count`, ou si les planchers de 1 % rendent le problème
    infaisable avec les contraintes du client, le portefeuille descend sous `min_count` et le diagnostic le dit.
    """
    minimum, maximum = int(holdings["min_count"]), int(holdings["max_count"])
    cost_limit = float(holdings.get("max_marginal_utility_cost", 0.0))
    floor = float(plan.minimum_held_weight)
    risky_n = len(plan.risky_symbols)
    required = {i for i in range(risky_n) if plan.lower_bounds[i] > 1e-9}
    order = [i for i in np.argsort(-w0[:risky_n]) if w0[i] > POSITIVE]
    keep = list(dict.fromkeys(sorted(required) + order))[: max(maximum, len(required))]
    dropped = [plan.symbols[i] for i in order if i not in keep]
    added, removed, notes = [], [], []
    w = w0

    from .optimizer import excess_variance, regularization_coefficients

    lambda_d, lambda_v, threshold = regularization_coefficients(settings)
    q = excess_variance(sigma, threshold)

    def marginal(current: np.ndarray) -> np.ndarray:
        """Gradient de l'utilité pénalisée: mu − A·Sigma·w − 2·lambda_D·w − 2·lambda_V·(q ⊙ w)."""
        w_r = current[:risky_n]
        return mu - aversion * (sigma @ w_r) - 2 * lambda_d * w_r - 2 * lambda_v * q * w_r

    def best_outside(current: np.ndarray, n: int, among=None) -> list[int]:
        gain = marginal(current)
        pool = [i for i in np.argsort(-gain) if i not in keep and (among is None or among(i))]
        return pool[:n]

    # 2. Le minimum de la plage (si l'univers le permet).
    while len(keep) < min(minimum, risky_n):
        batch = best_outside(w, min(10, minimum - len(keep)))
        if not batch:
            break
        keep += batch
        added += [plan.symbols[i] for i in batch]
        sub = restrict_plan(plan, keep, 0.0)
        try:  # nouveaux poids (sans plancher) pour réévaluer l'utilité marginale des titres restants
            idx = sorted(keep)
            sub_w = _continuous(sub, settings, mu[idx], sigma[np.ix_(idx, idx)], aversion)
            w = np.zeros_like(w0)
            w[idx] = sub_w[: len(idx)]
        except (ConstraintInfeasibleError, OptimizationError):
            pass
    # 3. Chaque groupe qui exige un poids > 0 doit avoir un membre.
    for g in plan.groups:
        if g.minimum > 1e-9 and not any(g.coefficients[i] > 1e-9 for i in keep):
            member = best_outside(w, 1, among=lambda i: i < risky_n and g.coefficients[i] > 1e-9)
            if member:
                keep += member
                added += [plan.symbols[member[0]]]
    # Planchers de 1 % infaisables avec les contraintes: retirer les titres d'utilité marginale la plus faible.
    gain = marginal(w)
    current = _floored(plan, settings, mu, sigma, aversion, keep)
    while current is None:
        removable = sorted((i for i in keep if i not in required), key=lambda i: gain[i])
        if not removable:
            raise ConstraintInfeasibleError(
                f"Aucun portefeuille ne respecte les contraintes avec {len(keep)} positions à {floor:.0%} ou plus.")
        keep.remove(removable[0])
        removed.append(plan.symbols[removable[0]])
        current = _floored(plan, settings, mu, sigma, aversion, keep)
    utility, w = current
    # 4. Diversifier tant que c'est presque gratuit.
    extended = 0
    while len(keep) < min(maximum, risky_n):
        batch = best_outside(w, min(5, maximum - len(keep)))
        if not batch:
            break
        trial = _floored(plan, settings, mu, sigma, aversion, keep + batch)
        if trial is None or (utility - trial[0]) / len(batch) > cost_limit:
            break
        keep += batch
        added += [plan.symbols[i] for i in batch]
        extended += len(batch)
        utility, w = trial
    if len(keep) < minimum:
        notes.append(f"{len(keep)} positions, sous le minimum de {minimum}: "
                     + (f"seulement {risky_n} titres admissibles." if risky_n < minimum
                        else "les contraintes du client ne permettent pas plus de positions à 1 % ou plus."))
    return sorted(keep), {"dropped_from_initial_optimum": dropped, "added_for_count": added,
                          "added_for_diversification": extended, "removed_for_feasibility": removed,
                          "count_notes": notes}


def _risk_contributions(weights: dict[str, float], sigma: pd.DataFrame, top: int = 5) -> list[dict]:
    symbols = list(weights)
    w = np.array([weights[s] for s in symbols])
    s = sigma.loc[symbols, symbols].to_numpy()
    marginal = s @ w
    total = float(w @ marginal)
    if total <= 0:
        return []
    rc = w * marginal / total
    return [{"symbol": symbols[i], "weight": round(float(w[i]), 4), "risk_share": round(float(rc[i]), 4)}
            for i in np.argsort(-rc)[:top]]


def optimize_universe(
    market: Market,
    objective: Objective,
    constraints: list[Constraint],
    *,
    vol_cap: Optional[float] = None,
    risk_aversion: Optional[float] = None,
    holdings: Optional[dict] = None,
) -> OptimizationResult:
    """Markowitz sur TOUS les titres qui passent le questionnaire et le filtre d'historique, sans sélection du LLM.

    mu: rendement espéré individuel (historique maximal de chaque titre, `Market.assets.ann_return`).
    Sigma: Ledoit-Wolf commune de l'univers (`Market.universe_covariance`), la même pour les trois variantes.
    """
    import time

    from .config import PORTFOLIO_HOLDINGS

    holdings = dict(holdings or market.settings.get("portfolio_holdings") or PORTFOLIO_HOLDINGS)
    # Un nombre de positions demandé explicitement par le client (min/max_positions) l'emporte sur la plage.
    hard = [c for c in constraints if c.hard]
    user_max = min([int(c.value) for c in hard if c.type is T.MAX_POSITIONS and c.value] or [0]) or None
    user_min = max([int(c.value) for c in hard if c.type is T.MIN_POSITIONS and c.value] or [0]) or None
    if user_max is not None:
        holdings["max_count"] = user_max
        holdings["min_count"] = min(holdings["min_count"], user_max)
    if user_min is not None:
        holdings["min_count"] = user_min
        holdings["max_count"] = max(holdings["max_count"], user_min)
    started = time.perf_counter()
    symbols, diag = universe_symbols(market, constraints)
    if not symbols:
        return OptimizationResult("infeasible", "Aucun titre ne passe les contraintes et le filtre d'historique.",
                                  diagnostics=diag)
    try:
        sigma_all, cov_diag = market.universe_covariance()
        plan = catalog.plan_for(market, symbols, constraints, risk_aversion=risk_aversion, verify=True)
        settings = catalog.settings_for(market, constraints, risk_aversion=risk_aversion)
    except (ConstraintInfeasibleError, ConstraintError) as exc:
        why = (" Le filtre d'historique a retiré des titres qui auraient pu la satisfaire: "
               f"{', '.join(diag['excluded_for_short_history'][:8])}." if diag["excluded_for_short_history"] else "")
        return OptimizationResult("infeasible", f"{exc}{why}", diagnostics=diag)
    diag["covariance"] = cov_diag
    risky = list(plan.risky_symbols)
    mu = market.assets.loc[risky, "ann_return"].to_numpy(dtype=float)
    sigma = sigma_all.loc[risky, risky].to_numpy(dtype=float)
    diag["assets_sent_to_markowitz"] = len(risky)
    aversion0 = {"min_volatility": A_MAX, "max_return": A_MIN}.get(objective, risk_aversion or A_MAX / 5)
    try:
        t = time.perf_counter()
        w0 = _continuous(plan, settings, mu, sigma, aversion0)
        diag["seconds_initial_optimization"] = round(time.perf_counter() - t, 2)
        diag["positive_weights_initial"] = int((w0[: len(risky)] > POSITIVE).sum())
        diag["weights_at_least_min_initial"] = int((w0[: len(risky)] >= holdings["min_held_weight"] - 1e-9).sum())
        u0 = _utility(w0[: len(risky)], mu, sigma, aversion0, settings)
        t = time.perf_counter()
        keep, selection = select_holdings(plan, settings, mu, sigma, aversion0, w0, holdings)
        diag.update(selection)
        diag["holdings_after_selection"] = len(keep)
        sub = restrict_plan(plan, keep, float(holdings["min_held_weight"]))
        sub_risky = list(sub.risky_symbols)
        sub_mu = pd.Series(market.assets.loc[sub_risky, "ann_return"].to_numpy(dtype=float), index=sub_risky)
        sub_sigma = sigma_all.loc[sub_risky, sub_risky]
        aversion = aversion0
        if objective == "max_sharpe":
            run, found = _best_sharpe(market, sub, settings, sub_mu, sub_sigma)
            if run is None:
                return OptimizationResult("infeasible", "Aucune pondération ne respecte les contraintes.",
                                          diagnostics=diag)
            aversion = found or aversion
        else:
            run = _solve(market, sub, settings, sub_mu, sub_sigma, aversion)
        cap = _volatility_cap(constraints, vol_cap)
        if cap is not None:
            run, aversion = _under_cap(market, sub, settings, sub_mu, sub_sigma, run, aversion, cap)
        diag["seconds_selection_and_reoptimization"] = round(time.perf_counter() - t, 2)
    except ConstraintInfeasibleError as exc:
        return OptimizationResult("infeasible", str(exc), diagnostics=diag)
    except (OptimizationError, ConstraintError) as exc:
        return OptimizationResult("infeasible", f"Optimisation impossible: {exc}", diagnostics=diag)

    weights = _weights(run)
    metrics = market.portfolio_metrics(weights)
    checks = evaluate(market, weights, [c for c in constraints if c.hard])
    failed = [c for c in checks if not c.passed]
    top = sorted(weights.values(), reverse=True)
    diag.update({
        "final_holdings": len(weights),
        "holdings_range": [int(holdings["min_count"]), int(holdings["max_count"])],
        "A_requested": risk_aversion, "A_initial_optimization": aversion0, "A_effective": aversion,
        "utility_initial_optimum": round(u0, 6), "utility_final": round(float(run.utility), 6),
        "effective_holdings_count": metrics.effective_n, "top_5_weight": round(sum(top[:5]), 4),
        "risk_contributions_top": _risk_contributions(weights, sigma_all),
        "active_bounds": sorted(s for s, w in weights.items()
                                if s in sub.symbols and abs(w - sub.upper_bounds[sub.index_of(s)]) < 1e-3),
        "constraints_satisfied": not failed,
        "seconds_total": round(time.perf_counter() - started, 2),
    })
    logger.info("Markowitz global: %s", {k: v for k, v in diag.items() if k != "excluded_by_questionnaire"})
    if failed:
        return OptimizationResult("infeasible", "Contraintes non respectées: " + "; ".join(
            f"{c.label} ({c.message})" for c in failed[:4]), weights=weights, metrics=metrics, failed_checks=failed,
            diagnostics=diag)
    status = "feasible" if run.notices else "optimal"
    message = (f"Markowitz global sur {len(risky)} titres, {len(weights)} positions détenues, "
               f"aversion au risque A = {aversion:g}.")
    if audit := catalog.audit(market, weights, constraints, risk_aversion=risk_aversion):
        status, message = "feasible", f"{message} Écart d'arrondi signalé par le moteur: {audit}"
    return OptimizationResult(status, message, weights=weights, metrics=metrics, diagnostics=diag)


__all__ = ["A_LADDER", "MIN_POSITION_WEIGHT", "Objective", "OptimizationResult", "optimize", "optimize_universe",
           "restrict_plan", "select_holdings", "universe_symbols"]
