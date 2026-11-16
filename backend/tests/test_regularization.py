"""Pénalités de diversification et de forte volatilité ajoutées à l'utilité de Markowitz.

U = w'mu − A/2·w'Sigma w − lambda_D·Σ w² − lambda_V·Σ q·w², q_i = max(0, Sigma_ii − 0,25²).
"""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest

from invest_agents import allocator, catalog, config, constraints, optimizer
from invest_agents.optimizer import excess_variance, regularization_gradient, regularization_penalty
from invest_agents.schemas import Constraint, ConstraintType as T
from test_global_markowitz import LIMITS, make_market


def cfg(lambda_d=0.0, lambda_v=0.0, threshold=0.25):
    c = config.get_agent_settings({"risk_aversion_A": 5.0})
    c["regularization"] = {"diversification_penalty": lambda_d, "high_volatility_penalty": lambda_v,
                           "volatility_threshold": threshold}
    return c


def toy(n_low=3, n_high=2):
    """Titres à 15 % de volatilité (sous le seuil) et à 45 % (au-dessus), rendements plus élevés pour les seconds."""
    names = [f"L{i}" for i in range(n_low)] + [f"H{i}" for i in range(n_high)]
    vols = np.array([0.15] * n_low + [0.45] * n_high)
    sigma = np.diag(vols ** 2)
    mu = np.array([0.05] * n_low + [0.12] * n_high)
    meta = pd.DataFrame({"asset_class": "Equity", "instrument_type": "Stock", "observations": 1000,
                         "is_included_universe": True}, index=pd.Index(names, name="symbol"))
    return names, pd.Series(mu, index=names), pd.DataFrame(sigma, index=names, columns=names), meta


def plan_of(c, meta):
    return constraints.build_constraint_plan(constraints.filter_eligible_universe(meta, c).universe, c)


def solve(c, mu, sigma, meta):
    return optimizer.optimize_weights(mu, sigma, plan_of(c, meta), c)


# 1. Coefficients nuls: l'objectif est celui de Markowitz.
def test_zero_coefficients_keep_markowitz():
    names, mu, sigma, meta = toy()
    w = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
    assert regularization_penalty(w, sigma.to_numpy(), 0.0, 0.0) == 0.0
    base = solve(cfg(), mu, sigma, meta)
    no_key = cfg()
    del no_key["regularization"]  # même résultat qu'un optimiseur sans la section
    legacy = optimizer.optimize_weights(mu, sigma, plan_of(cfg(), meta), no_key)
    pd.testing.assert_series_equal(base.weights, legacy.weights)
    x = base.weights[names].to_numpy()  # le plan trie les titres: on aligne par nom
    cash = base.cash_weight * cfg()["cash"]["annual_expected_return"]  # cash synthétique: sans variance
    assert base.utility == pytest.approx(x @ mu + cash - 0.5 * 5.0 * x @ sigma.to_numpy() @ x)


def test_defaults_in_config_are_zero_and_threshold_25():
    assert config.REGULARIZATION == {"diversification_penalty": 0.0, "high_volatility_penalty": 0.0,
                                     "volatility_threshold": 0.25}


# 2. La concentration coûte plus qu'une répartition égale.
def test_diversification_penalty_prefers_equal_weights():
    sigma = np.eye(4) * 0.04
    concentrated, equal = np.array([0.7, 0.1, 0.1, 0.1]), np.full(4, 0.25)
    assert regularization_penalty(concentrated, sigma, 0.5, 0.0) > regularization_penalty(equal, sigma, 0.5, 0.0)


def test_diversification_penalty_spreads_the_optimum():
    _, mu, sigma, meta = toy()
    before = solve(cfg(), mu, sigma, meta).weights
    after = solve(cfg(lambda_d=0.5), mu, sigma, meta).weights
    assert (after ** 2).sum() < (before ** 2).sum()  # HHI plus faible


# 3 à 6. Seuil de 25 %.
@pytest.mark.parametrize("vol, positive", [(0.10, False), (0.2499, False), (0.25, False), (0.2501, True), (0.60, True)])
def test_volatility_penalty_threshold(vol, positive):
    q = excess_variance(np.array([[vol ** 2]]), 0.25)
    penalty = regularization_penalty(np.array([0.5]), np.array([[vol ** 2]]), 0.0, 1.0)
    assert bool(q[0] > 0) is positive
    assert (penalty > 0) if positive else (penalty == 0.0)


def test_volatility_penalty_grows_with_excess_variance_at_equal_weight():
    sigma = np.diag([0.30 ** 2, 0.45 ** 2, 0.80 ** 2])
    each = [regularization_penalty(np.eye(3)[i] * 0.2, sigma, 0.0, 1.0) for i in range(3)]
    assert 0 < each[0] < each[1] < each[2]
    assert each[0] == pytest.approx(1.0 * (0.30 ** 2 - 0.25 ** 2) * 0.2 ** 2)


def test_volatility_penalty_reduces_weight_of_volatile_assets():
    _, mu, sigma, meta = toy()
    before = solve(cfg(), mu, sigma, meta).weights
    after = solve(cfg(lambda_v=2.0), mu, sigma, meta).weights
    assert after[["H0", "H1"]].sum() < before[["H0", "H1"]].sum()


# 7. Coefficients indépendants.
def test_coefficients_are_independent():
    sigma = np.diag([0.15 ** 2, 0.45 ** 2])
    w = np.array([0.6, 0.4])
    only_d = regularization_penalty(w, sigma, 0.3, 0.0)
    only_v = regularization_penalty(w, sigma, 0.0, 0.7)
    assert only_d == pytest.approx(0.3 * (w ** 2).sum())
    assert only_v == pytest.approx(0.7 * (0.45 ** 2 - 0.25 ** 2) * 0.4 ** 2)
    assert regularization_penalty(w, sigma, 0.3, 0.7) == pytest.approx(only_d + only_v)


def test_invalid_coefficients_are_refused():
    for key in ("diversification_penalty", "high_volatility_penalty", "volatility_threshold"):
        bad = cfg()
        bad["regularization"][key] = -0.1
        with pytest.raises(ValueError, match="non négatif"):
            config.validate_settings(bad)
        bad["regularization"][key] = float("nan")
        with pytest.raises(ValueError, match="fini"):
            config.validate_settings(bad)


# 8. La diagonale de Sigma annualisée, pas market.assets["ann_vol"].
def test_penalty_uses_covariance_diagonal_not_ann_vol(monkeypatch):
    m = make_market(n_us=20, n_ca=10, n_eu=4, n_etf_eq=4, n_bond=4, seed=2)
    m.assets["ann_vol"] = 0.01  # si l'optimiseur lisait cette colonne, aucune pénalité ne s'appliquerait
    sigma, _ = m.universe_covariance()
    volatile = [s for s in sigma.index if np.sqrt(sigma.loc[s, s]) > 0.25]
    assert volatile  # BTC-CAD au moins
    base = allocator.optimize_universe(m, "mean_variance", LIMITS, risk_aversion=3.0)
    assert sum(w for s, w in base.weights.items() if s in volatile) > 0.05  # rien à réduire sinon
    monkeypatch.setitem(config.REGULARIZATION, "high_volatility_penalty", 500.0)
    penalized = allocator.optimize_universe(m, "mean_variance", LIMITS, risk_aversion=3.0)
    weight = lambda r: sum(w for s, w in r.weights.items() if s in volatile)  # noqa: E731
    assert weight(penalized) < weight(base)


# 9. Gradient analytique cohérent avec l'objectif.
def test_gradient_matches_finite_differences():
    rng = np.random.default_rng(0)
    root = rng.normal(0, 0.2, (6, 6))
    sigma = root @ root.T + np.diag([0.01, 0.2, 0.05, 0.4, 0.02, 0.3])
    mu, w, a, ld, lv = rng.normal(0.08, 0.03, 6), rng.dirichlet(np.ones(6)), 4.0, 0.3, 0.8

    def objective(x):
        return -(x @ mu) + 0.5 * a * x @ sigma @ x + regularization_penalty(x, sigma, ld, lv)

    analytic = -mu + a * sigma @ w + regularization_gradient(w, sigma, ld, lv)
    eps = 1e-6
    numeric = np.array([(objective(w + eps * e) - objective(w - eps * e)) / (2 * eps) for e in np.eye(6)])
    assert np.allclose(analytic, numeric, atol=1e-6)


# 10. Les contraintes du questionnaire restent respectées.
def test_constraints_still_hold_with_penalties(monkeypatch):
    m = make_market(seed=4)
    monkeypatch.setitem(config.REGULARIZATION, "diversification_penalty", 0.2)
    monkeypatch.setitem(config.REGULARIZATION, "high_volatility_penalty", 3.0)
    cs = LIMITS + [Constraint(type=T.EXACT_ASSET_CLASS_WEIGHT, target="Fixed Income", value=0.30, hard=True),
                   Constraint(type=T.EXCLUDE_COUNTRY, target="France", hard=True)]
    r = allocator.optimize_universe(m, "mean_variance", cs, risk_aversion=7.0)
    assert r.ok, r.message
    a = m.assets
    assert sum(v for s, v in r.weights.items() if a.at[s, "asset_class"] == "Fixed Income") == pytest.approx(0.30, abs=2e-3)
    assert not any(a.at[s, "country"] == "France" for s in r.weights)
    assert min(r.weights.values()) >= 0.01 - 1e-4 and 25 <= len(r.weights) <= 70
    assert r.diagnostics["constraints_satisfied"]


# 11. Les trois variantes ont les mêmes coefficients; seul A change.
def test_variants_share_regularization(monkeypatch):
    monkeypatch.setitem(config.REGULARIZATION, "diversification_penalty", 0.1)
    m = make_market(n_us=10, n_ca=5, n_eu=2, n_etf_eq=2, n_bond=3, seed=1)
    settings = [catalog.settings_for(m, LIMITS, risk_aversion=a) for a in (8.32, 5.89, 4.16)]
    regs = [s["regularization"] for s in settings]
    assert regs[0] == regs[1] == regs[2] == {"diversification_penalty": 0.1, "high_volatility_penalty": 0.0,
                                            "volatility_threshold": 0.25}
    assert len({s["risk_aversion"]["default"] for s in settings}) == 3
