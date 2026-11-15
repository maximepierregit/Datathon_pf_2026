from __future__ import annotations

import argparse
import copy
import json
import math
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, linprog, minimize
from sklearn.covariance import LedoitWolf

from . import data
from .config import (
    get_agent_settings, get_base_settings, get_capm_benchmark,
    get_return_method, validate_settings,
)
from .constraints import (
    CandidateSelection, ConstraintInfeasibleError, ConstraintPlan,
    ScreeningResult, UnresolvedPreferenceError, assert_ready_for_optimization,
    build_constraint_plan, check_linear_feasibility, filter_eligible_universe,
    scipy_constraints, select_candidates, validate_weights,
)


class OptimizationError(RuntimeError):
    """Erreur de données ou de résolution du problème de portefeuille."""


class EstimationError(OptimizationError):
    """Estimations indisponibles/incohérentes, sans substitut inventé."""


@dataclass(frozen=True)
class ExpectedReturns:
    """Espérances ANNUELLES arithmétiques CAD, en fractions (0.08 = 8 %)."""
    annual: pd.Series
    details: pd.DataFrame
    notices: tuple[str, ...] = ()


@dataclass(frozen=True)
class CovarianceEstimate:
    """Matrice jointe annualisée dans l'ordre des actifs candidats."""
    annual: pd.DataFrame
    method: str
    observations: int
    shrinkage: float | None
    min_eigenvalue: float
    condition_number: float
    notices: tuple[str, ...] = ()


@dataclass(frozen=True)
class PortfolioResult:
    """Résultat de portefeuille ; les poids comprennent CASH-CAD si actif."""
    weights: pd.Series
    expected_return_annual: float
    volatility_annual: float
    variance_annual: float
    utility: float
    risk_aversion_A: float
    cash_weight: float
    solver_message: str
    solver_iterations: int
    cleanup_attempts: int
    notices: tuple[str, ...] = ()

    @property
    def invested_symbols(self) -> tuple[str, ...]:
        return tuple(self.weights.index[self.weights > 1e-7].astype(str))


@dataclass(frozen=True)
class OptimizationRun:
    """Trace complète et explicable d'un run BASE/AGENT."""
    screening: ScreeningResult
    selection: CandidateSelection
    plan: ConstraintPlan
    expected_returns: ExpectedReturns
    covariance: CovarianceEstimate
    portfolio: PortfolioResult


def _settings(cfg: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(cfg, Mapping) or cfg.get("execution_mode") not in {"base", "agent"}:
        raise OptimizationError("Passer get_base_settings() ou get_agent_settings(request).")
    validate_settings(cfg)
    return cfg


def _clean_returns(returns: pd.DataFrame, symbols: Sequence[str] | None = None) -> pd.DataFrame:
    """DataFrame dates × tickers, sans interpolation ni surprises numériques."""
    if not isinstance(returns, pd.DataFrame) or returns.empty:
        raise EstimationError("Matrice de rendements absente ou vide.")
    matrix = returns.copy()
    if not matrix.columns.is_unique:
        raise EstimationError("Tickers de rendement dupliqués.")
    if any(str(s) == "total_return_cad_fwd_1d" for s in matrix.columns):
        raise EstimationError("La colonne de rendement futur ne peut servir à l'estimation.")
    if symbols is not None:
        missing = [s for s in symbols if s not in matrix.columns]
        if missing:
            raise EstimationError(f"Rendements absents pour les candidats : {missing}.")
        matrix = matrix.loc[:, list(symbols)]
    if not matrix.index.is_unique:
        raise EstimationError("Dates dupliquées dans la matrice de rendements.")
    try:
        matrix.index = pd.DatetimeIndex(pd.to_datetime(matrix.index, errors="raise"))
    except (ValueError, TypeError) as exc:
        raise EstimationError("Dates de rendements invalides.") from exc
    if matrix.index.hasnans:
        raise EstimationError("Dates NaT interdites.")
    matrix = matrix.sort_index()
    try:
        matrix = matrix.apply(pd.to_numeric, errors="raise").astype(float)
    except (ValueError, TypeError) as exc:
        raise EstimationError("Rendements non numériques.") from exc
    if np.isinf(matrix.to_numpy()).any():
        raise EstimationError("Infini interdit dans les rendements.")
    # NaN conservés : pas de fillna(0), pas de ffill.
    return matrix


def _history(series: pd.Series, lookback: int | None) -> pd.Series:
    """Dernières observations DISPONIBLES propres au titre, sans inventer de dates."""
    observed = series.dropna()
    return observed if lookback is None else observed.iloc[-int(lookback):]


def _historical_mu(returns: pd.Series, lookback: int | None, minimum: int, periods: int) -> tuple[float, int]:
    obs = _history(returns, lookback)
    if len(obs) < minimum:
        raise EstimationError(f"{returns.name} : moyenne historique, {len(obs)} < {minimum} observations.")
    return float(obs.mean() * periods), len(obs)


def _ewma_mu(returns: pd.Series, lookback: int | None, minimum: int,
             half_life: float, periods: int) -> tuple[float, int]:
    obs = _history(returns, lookback)
    if len(obs) < minimum:
        raise EstimationError(f"{returns.name} : EWMA, {len(obs)} < {minimum} observations.")
    if not math.isfinite(float(half_life)) or half_life <= 0:
        raise EstimationError("La demi-vie EWMA doit être positive et finie.")
    age = np.arange(len(obs) - 1, -1, -1, dtype=float)
    weights = np.exp2(-age / float(half_life))
    weights /= weights.sum()
    return float(np.dot(weights, obs.to_numpy(dtype=float)) * periods), len(obs)


def _estimate_beta(
    asset: pd.Series, benchmark: pd.Series, lookback: int | None,
    minimum: int,
) -> tuple[float, int]:
    """Bêta OLS sur dates communes, avec variance de benchmark strictement positive."""
    paired = pd.concat([asset.rename("asset"), benchmark.rename("benchmark")], axis=1).dropna()
    paired = paired if lookback is None else paired.iloc[-int(lookback):]
    if len(paired) < minimum:
        raise EstimationError(
            f"Bêta {asset.name}/{benchmark.name} : {len(paired)} observations communes, minimum {minimum}.")
    benchmark_values = paired["benchmark"].to_numpy(dtype=float)
    asset_values = paired["asset"].to_numpy(dtype=float)
    variance = float(np.var(benchmark_values, ddof=1))
    if variance <= 1e-15:
        raise EstimationError(f"Benchmark {benchmark.name} : variance nulle, bêta non identifiable.")
    beta = float(np.cov(asset_values, benchmark_values, ddof=1)[0, 1] / variance)
    if not math.isfinite(beta):
        raise EstimationError(f"Bêta non fini pour {asset.name}.")
    return beta, len(paired)


def estimate_expected_returns(
    returns: pd.DataFrame,
    universe: pd.DataFrame,
    settings: Mapping[str, Any],
    *,
    benchmark_returns: pd.DataFrame | None = None,
) -> ExpectedReturns:
    """Calculer les 4 méthodes annuelles selon config.get_return_method.

    historical : 252 * moyenne quotidienne simple (max. ~5 ans).
    ewma       : 252 * moyenne à demi-vie 90 obs (toute l'histoire par défaut).
    capm_shrinkage : (1-alpha)*historical + alpha*(rf + beta*ERP).
    capm_benchmark_shrinkage : même formule, benchmark économique explicite,
      ERP spécifique au BENCHMARK obligatoirement renseigné.

    Le bêta est calculé sur observations appariées sans remplissage, la moyenne
    historique sur l'historique de l'actif. Toutes les séries restent CAD.
    """
    cfg = _settings(settings)
    if not isinstance(universe, pd.DataFrame) or universe.empty:
        raise EstimationError("Métadonnées des candidats absentes.")
    meta = universe.set_index("symbol") if "symbol" in universe.columns else universe
    names = tuple(str(s) for s in meta.index)
    if len(set(names)) != len(names):
        raise EstimationError("Tickers dupliqués dans les métadonnées.")
    matrix = _clean_returns(returns, names)
    available = (matrix if benchmark_returns is None or benchmark_returns.shape[1] == 0
                 else _clean_returns(benchmark_returns))
    # Les benchmarks hors univers investissable doivent avoir leurs retours historiques.
    # Reindex exclut automatiquement les dates non communes et tout futur hors panel.
    other = available.reindex(matrix.index)
    benchmark_matrix = other.combine_first(matrix)
    est = cfg["estimation"]
    periods = int(est["periods_per_year"])
    records: list[dict[str, Any]] = []
    values: dict[str, float] = {}
    for sym in names:
        row = meta.loc[sym]
        asset_class = str(row.get("asset_class", ""))
        instrument_type = str(row.get("instrument_type", ""))
        method = get_return_method(asset_class, instrument_type, symbol=sym, settings=cfg)
        sample = matrix[sym].rename(sym)
        bench: str | None = None
        beta: float | None = None
        n_beta: int | None = None
        if method == "historical":
            params = est["historical"]
            mean, n_mean = _historical_mu(sample, params["lookback_observations"],
                                           params["min_observations"], periods)
        elif method == "ewma":
            params = est["ewma"]
            mean, n_mean = _ewma_mu(sample, params["lookback_observations"],
                                     params["min_observations"],
                                     params["half_life_observations"], periods)
        elif method in {"capm_shrinkage", "capm_benchmark_shrinkage"}:
            params = est[method]
            hist, n_mean = _historical_mu(
                sample, params["historical_lookback_observations"],
                max(2, cfg["estimation"]["historical"]["min_observations"]), periods,
            )
            if method == "capm_shrinkage":
                bench = str(params["market_proxy"]).strip().upper()
                if instrument_type == "Cryptocurrency" or asset_class != "Equity":
                    raise EstimationError(f"CAPM marché unique non applicable sans justification à {sym}/{asset_class}.")
                erp = float(params["erp_annual"])
            else:
                bench = get_capm_benchmark(
                    sym, row.to_dict(), available_symbols=set(benchmark_matrix.columns), settings=cfg,
                )
                if bench is None:
                    raise EstimationError(f"Aucun benchmark économique vérifié pour {sym}.")
                erps = params["erp_annual_by_benchmark"]
                if bench not in erps:
                    raise EstimationError(
                        f"Prime de risque manquante pour benchmark {bench} (actif {sym}). "
                        "Renseigner erp_annual_by_benchmark dans config.py.")
                erp = float(erps[bench])
            if not bench or bench not in benchmark_matrix:
                raise EstimationError(
                    f"Benchmark CAPM {bench!r} absent pour {sym}. "
                    "Transmettre ses rendements CAD via benchmark_returns, même s'il est exclu du portefeuille.")
            benchmark_sample = benchmark_matrix[bench].rename(bench)
            beta, n_beta = _estimate_beta(sample, benchmark_sample,
                                         params["lookback_observations"],
                                         int(params["min_paired_observations"]))
            target = float(params["rf_annual"]) + beta * erp
            alpha = float(params["alpha"])
            mean = (1 - alpha) * hist + alpha * target
        else:
            raise EstimationError(f"Méthode de rendement inconnue : {method!r}.")
        if not math.isfinite(mean):
            raise EstimationError(f"Espérance annuelle non finie : {sym}.")
        values[sym] = float(mean)
        records.append({"symbol": sym, "method": method, "observations_mu": n_mean,
                        "benchmark": bench, "beta": beta, "paired_observations_beta": n_beta,
                        "expected_return_annual": float(mean)})
    return ExpectedReturns(
        annual=pd.Series(values, name="mu_annual", dtype=float),
        details=pd.DataFrame.from_records(records).set_index("symbol"),
    )


def estimate_covariance(
    returns: pd.DataFrame,
    settings: Mapping[str, Any],
    *,
    symbols: Sequence[str] | None = None,
) -> CovarianceEstimate:
    """Estimer Sigma jointe annualisée APRES sélection des candidats.

    LedoitWolf sklearn : intensité auto, cible identité redimensionnée (PAS
    constant-correlation), observations COMPLÈTES seulement sur les candidats.
    Sample : covariance pairwise avec recouvrement minimum ; projection PSD
    optionnelle si les observations manquantes créent des valeurs propres < 0.
    """
    cfg = _settings(settings)
    matrix = _clean_returns(returns, symbols)
    c = cfg["covariance"]
    lookback = c["lookback_observations"]
    if lookback is not None:
        matrix = matrix.tail(int(lookback))
    periods = int(c["periods_per_year"])
    minimum_each = int(c["min_observations_per_asset"])
    counts = matrix.count()
    insufficient = counts[counts < minimum_each]
    if not insufficient.empty:
        raise EstimationError(
            "Historique individuel insuffisant pour Sigma : "
            + ", ".join(f"{s}={n}" for s, n in insufficient.items()))
    method = c["method"]
    diag: list[str] = []
    shrinkage: float | None = None
    if method == "ledoit_wolf":
        if c["missing_policy_for_ledoit_wolf"] != "complete_cases_after_selection":
            raise EstimationError("Politique NaN Ledoit-Wolf non prise en charge.")
        clean = matrix.dropna(axis=0, how="any")
        observations = len(clean)
        min_joint = int(c["min_joint_observations"])
        if observations < min_joint:
            raise EstimationError(
                f"Ledoit-Wolf : seulement {observations} dates communes pour "
                f"{len(matrix.columns)} candidats (min={min_joint}). "
                "Réduire/revoir les candidats ou la fenêtre; ne PAS remplir les NaN.")
        model_params = c["ledoit_wolf"]
        model = LedoitWolf(
            assume_centered=bool(model_params["assume_centered"]),
            block_size=int(model_params["block_size"]),
        ).fit(clean.to_numpy(dtype=float))
        sigma = np.asarray(model.covariance_, dtype=float) * periods
        shrinkage = float(model.shrinkage_)
        # sklearn : estimateur à normalisation en n, différent de ddof=1.
        diag.append("LedoitWolf : covariance daily (n), cible scaled_identity, intensité auto.")
    elif method == "sample":
        observations = len(matrix)
        n_cols = len(matrix.columns)
        sigma = np.empty((n_cols, n_cols), dtype=float)
        overlap_min = int(c["sample"]["min_pairwise_observations"])
        for i in range(n_cols):
            for j in range(i, n_cols):
                pair = matrix.iloc[:, [i, j]] if i != j else matrix.iloc[:, [i]]
                paired = pair.dropna()
                if len(paired) < overlap_min:
                    raise EstimationError(
                        f"Covariance sample : {matrix.columns[i]}/{matrix.columns[j]}, "
                        f"{len(paired)} observations communes < {overlap_min}.")
                if i == j:
                    covariance_daily = float(paired.iloc[:, 0].var(ddof=1))
                else:
                    covariance_daily = float(paired.iloc[:, 0].cov(paired.iloc[:, 1]))
                sigma[i, j] = sigma[j, i] = covariance_daily * periods
        diag.append("Covariance empirique pairwise : réparée PSD uniquement si nécessaire.")
    else:
        raise EstimationError(f"Covariance : méthode inconnue {method}.")
    sigma = (sigma + sigma.T) / 2.0
    eigenvalues = np.linalg.eigvalsh(sigma)
    if eigenvalues[0] < -1e-10:
        if method == "sample" and c["sample"]["repair_psd"]:
            eig, vec = np.linalg.eigh(sigma)
            floor = float(c["sample"]["eigenvalue_floor"])
            sigma = (vec * np.maximum(eig, floor)) @ vec.T
            sigma = (sigma + sigma.T) / 2.0
            diag.append(f"Projection PSD appliquée : valeur propre min initiale={eig.min():.3g}.")
        else:
            raise EstimationError("Matrice de covariance non semi-définie positive.")
    if not np.isfinite(sigma).all():
        raise EstimationError("Matrice de covariance non finie.")
    vals = np.linalg.eigvalsh(sigma)
    return CovarianceEstimate(
        annual=pd.DataFrame(sigma, index=matrix.columns, columns=matrix.columns),
        method=method, observations=observations,
        shrinkage=shrinkage, min_eigenvalue=float(vals.min()),
        condition_number=float(np.linalg.cond(sigma)), notices=tuple(diag),
    )


def _linear_lp(plan: ConstraintPlan, low: np.ndarray, high: np.ndarray) -> np.ndarray | None:
    """Point de départ réalisable sous budget + groupes + bornes proposées."""
    aub: list[np.ndarray] = []
    bub: list[float] = []
    for group in plan.groups:
        if math.isfinite(group.maximum):
            aub.append(group.coefficients)
            bub.append(float(group.maximum))
        if math.isfinite(group.minimum):
            aub.append(-group.coefficients)
            bub.append(-float(group.minimum))
    if (np.any(low > high + 1e-10) or low.sum() > 1 + 1e-9
            or high.sum() < 1 - 1e-9):
        return None
    lp = linprog(np.zeros(len(plan.symbols)),
                 A_ub=np.vstack(aub) if aub else None,
                 b_ub=np.asarray(bub) if bub else None,
                 A_eq=np.ones((1, len(plan.symbols))), b_eq=[1.0],
                 bounds=list(zip(low, high)), method="highs")
    return lp.x if lp.success else None


def _solve_slsqp(
    mu: np.ndarray, sigma: np.ndarray, A: float, plan: ConstraintPlan,
    cfg: Mapping[str, Any], lower: np.ndarray, upper: np.ndarray,
    initial: np.ndarray,
) -> tuple[np.ndarray, str, int]:
    """SLSQP avec gradient analytique et contraintes linéaires d'origine."""
    def negative_utility(w: np.ndarray) -> float:
        return float(-w @ mu + 0.5 * A * (w @ sigma @ w))

    def derivative(w: np.ndarray) -> np.ndarray:
        return -mu + A * sigma @ w

    _, groups = scipy_constraints(plan)
    result = minimize(
        negative_utility, x0=initial, jac=derivative, method="SLSQP",
        bounds=Bounds(lower, upper), constraints=groups,
        options=dict(cfg["optimization"]["solver_options"]),
    )
    if not result.success:
        raise OptimizationError(f"SLSQP ne converge pas : {result.message}")
    if not np.isfinite(result.x).all():
        raise OptimizationError("SLSQP a retourné des poids non finis.")
    return np.asarray(result.x, dtype=float), str(result.message), int(result.nit)


def _active_set_plan(plan: ConstraintPlan, kept: set[int]) -> tuple[np.ndarray, np.ndarray]:
    """Positions risquées non retenues figées à zéro; positions retenues >=1%."""
    low = plan.lower_bounds.copy()
    high = plan.upper_bounds.copy()
    for i, sym in enumerate(plan.risky_symbols):
        if i in kept:
            low[i] = max(low[i], plan.minimum_held_weight)
        else:
            if low[i] > plan.constraint_tolerance:
                raise ConstraintInfeasibleError(f"Impossible d'exclure le titre obligatoire {sym}.")
            low[i] = high[i] = 0.0
    return low, high


def optimize_weights(
    mu: ExpectedReturns | pd.Series,
    covariance: CovarianceEstimate | pd.DataFrame,
    plan: ConstraintPlan,
    settings: Mapping[str, Any],
) -> PortfolioResult:
    """Optimiser sous contrainte (budget, bornes, groupes, cash, 1% disjonctif).

    1. Résolution continue (LP initial puis SLSQP analytique).
    2. Si micro-positions (0 < w < 1%), fixer celles-ci à 0, mettre les autres
       positions retenues à >=1%, puis réoptimiser. Si impossible, réintroduire
       progressivement les micro-positions, avec leur plancher de 1%.
    3. Audit final strict par constraints.validate_weights.

    Heuristique et non MIQP global; si infeasible, remonter l'erreur, jamais
    forcer une allocation violant les préférences ou introduire des actifs.
    """
    cfg = _settings(settings)
    if not isinstance(plan, ConstraintPlan):
        raise OptimizationError("ConstraintPlan absent (filtrer et construire avant l'optimisation).")
    assert_ready_for_optimization(plan)  # less/more non calibrées interdites
    check_linear_feasibility(plan)
    if cfg["optimization"]["solver"] != "SLSQP":
        raise OptimizationError("Solveur attendu : SLSQP.")

    raw_mu = mu.annual if isinstance(mu, ExpectedReturns) else mu
    raw_sigma = covariance.annual if isinstance(covariance, CovarianceEstimate) else covariance
    if not isinstance(raw_mu, pd.Series) or not isinstance(raw_sigma, pd.DataFrame):
        raise OptimizationError("mu doit être pd.Series et Sigma pd.DataFrame (indexées par ticker).")
    risky = list(plan.risky_symbols)
    if not all(s in raw_mu.index for s in risky):
        raise OptimizationError(f"Rendements absents : {sorted(set(risky) - set(raw_mu.index))}")
    if not all(s in raw_sigma.index and s in raw_sigma.columns for s in risky):
        raise OptimizationError("Sigma ne contient pas tous les candidats.")
    annual_mu = raw_mu.loc[risky].to_numpy(dtype=float)
    annual_sigma = raw_sigma.loc[risky, risky].to_numpy(dtype=float)
    if plan.cash_symbol:
        annual_mu = np.append(annual_mu, float(cfg["cash"]["annual_expected_return"]))
        augmented = np.zeros((len(plan.symbols), len(plan.symbols)), dtype=float)
        augmented[:len(risky), :len(risky)] = annual_sigma
        annual_sigma = augmented
        if not cfg["cash"]["zero_covariance_assumption"] or cfg["cash"]["annual_volatility"] != 0:
            raise OptimizationError("Cash non nul en risque : fournir modèle de covariance explicite.")
    if len(annual_mu) != len(plan.symbols):
        raise OptimizationError("Dimension mu et ConstraintPlan incohérente.")
    if not np.isfinite(annual_mu).all() or not np.isfinite(annual_sigma).all():
        raise OptimizationError("Paramètres mu/Sigma non finis.")
    annual_sigma = (annual_sigma + annual_sigma.T) / 2
    if np.linalg.eigvalsh(annual_sigma).min() < -1e-8:
        raise OptimizationError("Sigma non positive semi-définie : l'optimiseur la refuse.")
    A = float(cfg["risk_aversion"]["default"])
    if not 0 < A < math.inf:
        raise OptimizationError("Aversion au risque A invalide.")

    low = plan.lower_bounds.copy()
    high = plan.upper_bounds.copy()
    initial = _linear_lp(plan, low, high)
    if initial is None:
        raise ConstraintInfeasibleError("Budget/groupes/bornes : problème linéaire impossible.")
    w, msg, niter = _solve_slsqp(annual_mu, annual_sigma, A, plan, cfg, low, high, initial)
    attempts = 0
    notices: list[str] = []
    tol = plan.constraint_tolerance
    micro = [i for i in range(len(risky)) if tol < w[i] < plan.minimum_held_weight - tol]
    if micro:
        # Ne jamais écarter un titre obligatoire, même si la solution continue
        # était numériquement insuffisante.
        required_i = {plan.index_of(s) for s in plan.required_symbols}
        support = {i for i in range(len(risky))
                   if w[i] >= plan.minimum_held_weight - tol or i in required_i}
        pending = sorted((i for i in range(len(risky)) if i not in support),
                         key=lambda i: (-w[i], plan.symbols[i]))
        # Augmenter le support seulement si le premier support est impossible.
        # Maximum <= nombre d'actifs: terminaison et pas de boucle infinie.
        candidate_start: np.ndarray | None = None
        while True:
            attempts += 1
            low_active, high_active = _active_set_plan(plan, support)
            candidate_start = _linear_lp(plan, low_active, high_active)
            if candidate_start is not None:
                break
            if not pending:
                raise ConstraintInfeasibleError(
                    "La règle 0 ou >=1 % rend le portefeuille infaisable "
                    "avec les autres limites (cash, groupes, titres obligatoires).")
            support.add(pending.pop(0))
        w, msg_2, new_iterations = _solve_slsqp(
            annual_mu, annual_sigma, A, plan, cfg, low_active, high_active, candidate_start,
        )
        niter += new_iterations
        msg = f"{msg} ; nettoyage : {msg_2}"
        notices.append(
            f"Prune/reoptimize : {len(risky)-len(support)} positions facultatives fixées à zéro; "
            "solution locale, non nécessairement globale.")
    # Petites erreurs numériques de solveur peuvent être interdites par l'audit.
    validate_weights(w, plan, enforce_minimum_holding=True)
    expected = float(w @ annual_mu)
    variance = max(0.0, float(w @ annual_sigma @ w))
    return PortfolioResult(
        weights=pd.Series(w, index=plan.symbols, name="weight"),
        expected_return_annual=expected,
        volatility_annual=float(np.sqrt(variance)),
        variance_annual=variance,
        utility=float(expected - 0.5 * A * variance),
        risk_aversion_A=A,
        cash_weight=float(w[plan.index_of(plan.cash_symbol)]) if plan.cash_symbol else 0.0,
        solver_message=msg,
        solver_iterations=niter,
        cleanup_attempts=attempts,
        notices=tuple(notices),
    )


def _needed_benchmarks(meta: pd.DataFrame, cfg: Mapping[str, Any], available: set[str]) -> tuple[str, ...]:
    """Lister les proxies nécessaires aux mu CAPM, sans les rendre investissables."""
    required: set[str] = set()
    for sym, row in meta.iterrows():
        method = get_return_method(str(row.get("asset_class")), str(row.get("instrument_type")),
                                   symbol=sym, settings=cfg)
        if method == "capm_shrinkage":
            required.add(str(cfg["estimation"][method]["market_proxy"]).upper())
        elif method == "capm_benchmark_shrinkage":
            proxy = get_capm_benchmark(sym, row.to_dict(),
                                       available_symbols=available, settings=cfg)
            if proxy is None:
                raise EstimationError(f"Benchmark CAPM personnalisé manquant pour {sym}.")
            required.add(proxy)
    missing = required - available
    if missing:
        raise EstimationError(f"Benchmarks absents du Parquet : {sorted(missing)}.")
    return tuple(sorted(required))


def optimize_portfolio(
    panel: pd.DataFrame,
    settings: Mapping[str, Any],
    *,
    universe: pd.DataFrame | None = None,
    exposure_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    selection_returns: pd.DataFrame | None = None,
) -> OptimizationRun:
    """Pipeline complet pour panel NORMALISÉ, non encore optimisé.

    Filtrage (contraintes hard) -> candidats -> mu/Sigma sur candidats ->
    plan des bornes -> solveur -> audit des poids. Les benchmark_returns sont
    générés depuis le panel complet, même pour un ETF exclu des candidats.

    L'orchestrateur doit appeler data.filter_market_data (as_of/start_date) en
    AMONT ou s'appuyer sur les paramètres de data dans la fonction présente.
    """
    cfg = _settings(settings)
    if not isinstance(panel, pd.DataFrame):
        raise OptimizationError("panel doit être un DataFrame normalisé par data.py.")
    # Vérifier AVANT toute opération temporelle : des métadonnées préparées
    # sur une date future pourraient contaminer le filtrage à as_of.
    if universe is not None and (cfg["data"]["as_of"] is not None or cfg["data"]["start_date"] is not None):
        raise OptimizationError("Univers préconstruit + as_of/start_date : risque de fuite temporelle. Recalculer l'univers.")
    # Exclure la colonne forward, même si le panel brut la contient.
    clean_panel = panel.drop(columns=[cfg["data"]["forward_return_column"]], errors="ignore")
    clean_panel = data.filter_market_data(
        clean_panel, as_of=cfg["data"]["as_of"], start_date=cfg["data"]["start_date"],
    )
    full_universe = (data.build_universe(
        clean_panel, region_overrides=cfg["data"]["region_overrides"],
    ) if universe is None else universe)
    screened = filter_eligible_universe(full_universe, cfg, exposure_overrides=exposure_overrides)
    selected = select_candidates(screened, cfg, returns=selection_returns,
                                 exposure_overrides=exposure_overrides)
    plan = build_constraint_plan(selected, cfg, exposure_overrides=exposure_overrides)
    assert_ready_for_optimization(plan)
    check_linear_feasibility(plan)
    # Estimation UNIQUEMENT sur les actifs retenus.
    returns = data.build_returns_matrix(clean_panel, selected.symbols)
    observed_symbols = set(clean_panel["symbol"].astype(str).str.upper())
    proxies = _needed_benchmarks(selected.universe, cfg, observed_symbols)
    benchmark_returns = (data.build_returns_matrix(clean_panel, proxies)
                         if proxies else pd.DataFrame(index=returns.index))
    mu = estimate_expected_returns(returns, selected.universe, cfg,
                                   benchmark_returns=benchmark_returns)
    sigma = estimate_covariance(returns, cfg, symbols=plan.risky_symbols)
    result = optimize_weights(mu, sigma, plan, cfg)
    return OptimizationRun(screened, selected, plan, mu, sigma, result)


def optimize_from_parquet(
    settings: Mapping[str, Any], *,
    s3_client: Any | None = None,
    exposure_overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> OptimizationRun:
    """Charger une seule fois le Parquet local/S3 puis lancer le pipeline."""
    cfg = _settings(settings)
    raw = data.load_market_data(cfg["data"]["parquet_source"], s3_client=s3_client)
    raw = raw.drop(columns=[cfg["data"]["forward_return_column"]], errors="ignore")
    clean = data.normalize_market_data(raw)
    data.validate_market_data(clean, strict=cfg["data"]["strict_validation"])
    return optimize_portfolio(clean, cfg, exposure_overrides=exposure_overrides)


def main() -> None:
    """Commande volontairement simple; mode AGENT exige sa requête JSON."""
    parser = argparse.ArgumentParser(description="AlphaForge — optimisation Markowitz")
    parser.add_argument("--mode", choices=("base", "agent"), default="base")
    parser.add_argument("--request-json", default=None,
                        help='Mode agent: {"risk_aversion_A":5,"min_cash_weight":0.1}')
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()
    if args.mode == "base":
        if args.request_json is not None:
            parser.error("Mode BASE : request-json interdit.")
        cfg = get_base_settings()
    else:
        if args.request_json is None:
            parser.error("Mode AGENT : --request-json obligatoire.")
        cfg = get_agent_settings(json.loads(args.request_json))
    run = optimize_from_parquet(cfg)
    weights = run.portfolio.weights.sort_values(ascending=False)
    print("RUN", cfg["execution_mode"].upper(), "/", len(run.selection.symbols), "candidats")
    print("Rendement annuel espéré :", f"{run.portfolio.expected_return_annual:.2%}")
    print("Volatilité annualisée :", f"{run.portfolio.volatility_annual:.2%}")
    print("Utilité :", f"{run.portfolio.utility:.6f}")
    print("Cash :", f"{run.portfolio.cash_weight:.2%}")
    print("Shrinkage LedoitWolf :", run.covariance.shrinkage)
    print((100 * weights.head(args.top)).round(2).to_string() + " (% du portefeuille)")


__all__ = [
    "CovarianceEstimate", "EstimationError", "ExpectedReturns", "OptimizationError",
    "OptimizationRun", "PortfolioResult", "estimate_covariance", "estimate_expected_returns",
    "optimize_from_parquet", "optimize_portfolio", "optimize_weights",
]

if __name__ == "__main__":
    main()
