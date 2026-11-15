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


__all__ = ["A_LADDER", "MIN_POSITION_WEIGHT", "Objective", "OptimizationResult", "optimize"]
