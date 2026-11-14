"""Optimisation de portefeuille sous contraintes (moyenne-variance, SLSQP).

Seules les contraintes dures sont imposées à l'optimiseur. Les préférences (hard=False) sont
évaluées après coup par le Juge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Optional

import numpy as np
from scipy.optimize import minimize

from .config import get_settings
from .constraints import ANY, DIMENSION_COLUMN, SPECS, evaluate, excluded_mask
from .data import UNKNOWN
from .data import Market
from .schemas import Constraint, ConstraintCheck, ConstraintType as T, PortfolioMetrics

Objective = Literal["min_volatility", "max_sharpe", "max_return"]
MIN_POSITION_WEIGHT = 0.01  # chaque titre retenu pèse au moins 1 %


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


def _group_vector(market: Market, symbols: list[str], dimension: str, target: str) -> np.ndarray:
    t = target.lower()
    if dimension == "symbol":
        return np.array([1.0 if s.lower() == t else 0.0 for s in symbols])
    col = DIMENSION_COLUMN[dimension]
    values = market.assets.loc[symbols, col].str.lower()
    return (values == t).to_numpy(dtype=float)


def optimize(
    market: Market,
    symbols: list[str],
    objective: Objective,
    constraints: list[Constraint],
    *,
    vol_cap: Optional[float] = None,
) -> OptimizationResult:
    """Optimise les poids d'une sélection de titres.

    `vol_cap` est un plafond de volatilité propre au mandat. Il s'ajoute aux contraintes de l'utilisateur
    (le plus strict gagne). Il est indispensable pour `max_return`, sinon le résultat se concentre.
    """
    s = get_settings()
    hard = [c for c in constraints if c.hard]

    # --- Validation de la sélection ------------------------------------------------------------
    seen: set[str] = set()
    unique = [x for x in symbols if not (x in seen or seen.add(x))]
    unknown = [x for x in unique if x not in market.assets.index]
    if unknown:
        return OptimizationResult("invalid_selection", f"Symboles absents de l'univers: {', '.join(unknown)}")
    banned = excluded_mask(market, hard)
    forbidden = [x for x in unique if bool(banned.get(x, False))]
    if forbidden:
        return OptimizationResult(
            "invalid_selection", f"Symboles exclus par les contraintes de l'utilisateur: {', '.join(forbidden)}"
        )
    syms = unique
    n = len(syms)
    max_n = min(
        [s.max_assets_per_portfolio]
        + [int(c.value) for c in hard if c.type is T.MAX_POSITIONS and c.value]
    )
    min_n = max([int(c.value) for c in hard if c.type is T.MIN_POSITIONS and c.value] + [1])
    if n > max_n:
        return OptimizationResult("invalid_selection", f"Trop de titres ({n}). Maximum autorisé: {max_n}.")
    if n < min_n:
        return OptimizationResult("invalid_selection", f"Pas assez de titres ({n}). Minimum requis: {min_n}.")

    # --- Bornes --------------------------------------------------------------------------------
    lb = np.full(n, MIN_POSITION_WEIGHT)
    ub = np.ones(n)
    for c in hard:
        if c.type is T.MAX_POSITION_WEIGHT and c.value is not None:
            ub = np.minimum(ub, c.value)
        elif c.type in (T.MAX_SYMBOL_WEIGHT, T.MIN_SYMBOL_WEIGHT):
            vec = _group_vector(market, syms, "symbol", c.target or "")
            if vec.sum() == 0:
                if c.type is T.MIN_SYMBOL_WEIGHT:
                    return OptimizationResult(
                        "invalid_selection", f"Le titre {c.target} doit être détenu (poids minimal) mais n'est pas dans la sélection."
                    )
                continue
            idx = int(vec.argmax())
            if c.type is T.MAX_SYMBOL_WEIGHT:
                ub[idx] = min(ub[idx], c.value or 1.0)
            else:
                lb[idx] = max(lb[idx], c.value or 0.0)
    if (lb > ub + 1e-12).any():
        return OptimizationResult("infeasible", "Bornes incompatibles: un titre a un poids minimal supérieur à son plafond.")
    if lb.sum() > 1 + 1e-9:
        return OptimizationResult("infeasible", "Trop de titres pour respecter le poids minimal de 1 % par position.")
    if ub.sum() < 1 - 1e-9:
        need = int(np.ceil(1 / ub.max()))
        return OptimizationResult(
            "infeasible", f"Pas assez de titres pour atteindre 100 % avec le plafond par titre. Sélectionner au moins {need} titres."
        )

    # --- Contraintes de groupe, volatilité, rendement -----------------------------------------
    mu, cov = market.moments(syms)
    cons: list[dict] = [{"type": "eq", "fun": lambda w: w.sum() - 1.0, "jac": lambda w: np.ones_like(w)}]
    for c in hard:
        spec = SPECS[c.type]
        if spec.dimension and spec.kind == "fraction" and c.target == ANY:
            col = DIMENSION_COLUMN[spec.dimension]
            for group in sorted(set(market.assets.loc[syms, col]) - {UNKNOWN}):
                vec = _group_vector(market, syms, spec.dimension, group)
                cons.append({"type": "ineq", "fun": lambda w, a=vec, v=float(c.value or 0): v - a @ w, "jac": lambda w, a=vec: -a})
            continue
        if spec.dimension and spec.kind == "fraction":
            vec = _group_vector(market, syms, spec.dimension, c.target or "")
            v = float(c.value or 0.0)
            if spec.direction == "min" and vec.sum() == 0 and v > 0:
                return OptimizationResult(
                    "infeasible",
                    f"Aucun titre de la sélection n'appartient à {c.target}, alors qu'un poids minimal de {v:.0%} est exigé.",
                )
            if c.type in (T.MAX_SYMBOL_WEIGHT, T.MIN_SYMBOL_WEIGHT):
                continue  # déjà traité dans les bornes
            if spec.direction == "max":
                cons.append({"type": "ineq", "fun": lambda w, a=vec, v=v: v - a @ w, "jac": lambda w, a=vec: -a})
            else:
                cons.append({"type": "ineq", "fun": lambda w, a=vec, v=v: a @ w - v, "jac": lambda w, a=vec: a})

    caps = [c.value for c in hard if c.type is T.MAX_VOLATILITY and c.value is not None]
    if vol_cap is not None:
        caps.append(vol_cap)
    if caps:
        cap = float(min(caps))
        cons.append(
            {"type": "ineq", "fun": lambda w, cap=cap: cap**2 - w @ cov @ w, "jac": lambda w: -2 * cov @ w}
        )
    for c in hard:
        if c.type is T.MIN_EXPECTED_RETURN and c.value is not None:
            cons.append({"type": "ineq", "fun": lambda w, r=c.value: mu @ w - r, "jac": lambda w: mu})

    # --- Objectif ------------------------------------------------------------------------------
    rf = s.risk_free_rate
    fun: Callable[[np.ndarray], float]
    if objective == "min_volatility":
        fun = lambda w: float(w @ cov @ w)  # noqa: E731
        jac: Callable[[np.ndarray], np.ndarray] = lambda w: 2 * cov @ w  # noqa: E731
    elif objective == "max_return":
        fun = lambda w: float(-(mu @ w))  # noqa: E731
        jac = lambda w: -mu  # noqa: E731
    else:

        def fun(w: np.ndarray) -> float:
            return float(-(mu @ w - rf) / np.sqrt(max(w @ cov @ w, 1e-12)))

        jac = None  # type: ignore[assignment]

    x0 = np.clip(np.full(n, 1.0 / n), lb, ub)
    x0 = x0 / x0.sum()
    res = minimize(fun, x0, jac=jac, bounds=list(zip(lb, ub)), constraints=cons, method="SLSQP",
                   options={"maxiter": 500, "ftol": 1e-10})

    w = np.round(np.clip(res.x, lb, ub), 4)
    residual = round(1.0 - w.sum(), 4)  # résidu d'arrondi, placé là où il reste de la marge
    if residual > 0:
        w[int(np.argmax(ub - w))] += residual
    elif residual < 0:
        w[int(np.argmax(w - lb))] += residual
    w = np.clip(w, lb, ub)
    weights = {sym: float(wi) for sym, wi in zip(syms, w)}

    # --- Vérification indépendante du résultat ------------------------------------------------
    hard_eff = list(hard)
    if vol_cap is not None:
        hard_eff.append(Constraint(type=T.MAX_VOLATILITY, value=vol_cap, source="profile", note="plafond du mandat"))
    checks = evaluate(market, weights, hard_eff)
    failed = [c for c in checks if not c.passed]
    metrics = market.portfolio_metrics(weights)
    if failed:
        detail = "; ".join(f"{c.label} ({c.message})" for c in failed)
        return OptimizationResult(
            "infeasible",
            f"Aucune allocation ne respecte toutes les contraintes dures avec cette sélection. Écarts: {detail}. "
            "Changer la sélection (plus de titres défensifs, titres des secteurs exigés) ou la taille du portefeuille.",
            weights=weights,
            metrics=metrics,
            failed_checks=failed,
        )
    status = "optimal" if res.success else "feasible"
    msg = "Optimisation réussie." if res.success else f"Solution admissible mais non convergée ({res.message})."
    return OptimizationResult(status, msg, weights=weights, metrics=metrics)
