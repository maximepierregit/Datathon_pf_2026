"""Tests métier de optimizer.py, indépendants du vrai Parquet et d'AWS.

Vérifie les estimateurs, l'alignement des benchmarks, Ledoit-Wolf, la
projection PSD, les contraintes Markowitz, cash, micro-positions, profils,
API de pipeline, et les erreurs explicites.
"""
from __future__ import annotations

import copy
import math

import numpy as np
import pandas as pd
import pytest

from invest_agents import config, constraints, optimizer


def cfg_hist():
    c = config.get_base_settings()
    c["estimation"]["mode"] = "single_method"
    c["estimation"]["single_method"] = "historical"
    return c


def cfg_agent_hist(request=None):
    c = config.get_agent_settings({"risk_aversion_A": 5.0, **(request or {})})
    c["estimation"]["mode"] = "single_method"
    c["estimation"]["single_method"] = "historical"
    return c


def sample_dataset(n=160):
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2025-01-01", periods=n)
    spy = rng.normal(0.0004, 0.012, n)
    nvda = 1.5 * spy + rng.normal(0, 0.006, n)
    aapl = 0.9 * spy + rng.normal(0, 0.006, n)
    bond = rng.normal(0.00012, 0.002, n)
    crypto = rng.normal(0.001, 0.025, n)
    mat = pd.DataFrame({"SPY": spy, "NVDA": nvda, "AAPL": aapl,
                        "XBB.TO": bond, "BTC-CAD": crypto}, index=dates)
    meta = pd.DataFrame([
        ("SPY", "Equity", "ETF", "Non classé", "Non classé", "Non classé", "us", "core"),
        ("NVDA", "Equity", "Stock", "United States", "Information Technology", "us", "us", "ia;tech"),
        ("AAPL", "Equity", "Stock", "United States", "Information Technology", "us", "us", "tech"),
        ("XBB.TO", "Fixed Income", "ETF", "Non classé", "Non classé", "Non classé", "", "bonds"),
        ("BTC-CAD", "Alternative", "Cryptocurrency", "Non classé", "Non classé", "", "", "crypto"),
    ], columns=["symbol", "asset_class", "instrument_type", "country", "sector", "region", "market", "theme"])
    meta["observations"] = n
    meta["is_included_universe"] = True
    meta = meta.set_index("symbol")
    return mat, meta


def plan_for(meta, cfg):
    screen = constraints.filter_eligible_universe(meta, cfg)
    return constraints.build_constraint_plan(screen.universe, cfg)


def manual_mu_cov(meta, mus, sigma_value=0.04):
    names = list(meta.index)
    mu = pd.Series(mus, index=names, dtype=float)
    cov = pd.DataFrame(np.eye(len(names)) * sigma_value, index=names, columns=names)
    return mu, cov


def test_01_historical_mean_annualization_and_bond():
    mat, meta = sample_dataset()
    cfg = cfg_hist()
    est = optimizer.estimate_expected_returns(mat, meta, cfg)
    assert est.annual["XBB.TO"] == pytest.approx(mat["XBB.TO"].mean() * 252)
    assert est.details.loc["XBB.TO", "method"] == "historical"


def test_02_historical_lookback_uses_last_non_null():
    mat, meta = sample_dataset()
    cfg = cfg_hist()
    cfg["estimation"]["historical"]["lookback_observations"] = 120
    mat.iloc[-1, mat.columns.get_loc("NVDA")] = np.nan
    got = optimizer.estimate_expected_returns(mat, meta, cfg)
    assert got.annual["NVDA"] == pytest.approx(mat["NVDA"].dropna().tail(120).mean() * 252)


def test_03_ewma_full_history_and_weights():
    mat, meta = sample_dataset()
    cfg = cfg_hist()
    cfg["estimation"]["single_method"] = "ewma"
    result = optimizer.estimate_expected_returns(mat, meta, cfg)
    obs = mat["AAPL"].to_numpy()
    weights = 2 ** (-np.arange(len(obs)-1, -1, -1) / 90)
    assert result.annual["AAPL"] == pytest.approx(np.average(obs, weights=weights) * 252)


def test_04_ewma_recent_data_weighted_more():
    mat, meta = sample_dataset()
    cfg = cfg_hist()
    cfg["estimation"]["single_method"] = "ewma"
    orig = optimizer.estimate_expected_returns(mat, meta, cfg).annual["NVDA"]
    mat.iloc[-1, mat.columns.get_loc("NVDA")] += 0.2
    late = optimizer.estimate_expected_returns(mat, meta, cfg).annual["NVDA"]
    assert late > orig


def test_05_capm_shrinkage_beta_and_alpha():
    mat, meta = sample_dataset()
    cfg = config.get_base_settings()
    cfg["estimation"]["mode"] = "single_method"
    cfg["estimation"]["single_method"] = "capm_shrinkage"
    est = optimizer.estimate_expected_returns(mat[["NVDA"]], meta.loc[["NVDA"]], cfg,
                                               benchmark_returns=mat[["SPY"]])
    expected_beta = mat["NVDA"].cov(mat["SPY"]) / mat["SPY"].var(ddof=1)
    expected = 0.5 * 252 * mat["NVDA"].mean() + 0.5 * (0.035 + expected_beta * 0.05)
    assert est.annual["NVDA"] == pytest.approx(expected)
    assert est.details.loc["NVDA", "beta"] == pytest.approx(expected_beta)


def test_06_capm_missing_benchmark_rejected():
    mat, meta = sample_dataset()
    cfg = config.get_base_settings()
    cfg["estimation"]["mode"] = "single_method"
    cfg["estimation"]["single_method"] = "capm_shrinkage"
    with pytest.raises(optimizer.EstimationError, match="Benchmark"):
        optimizer.estimate_expected_returns(mat[["NVDA"]], meta.loc[["NVDA"]], cfg)


def test_07_capm_benchmark_requires_erp():
    mat, meta = sample_dataset()
    cfg = config.get_base_settings()
    cfg["estimation"]["mode"] = "single_method"
    cfg["estimation"]["single_method"] = "capm_benchmark_shrinkage"
    with pytest.raises(optimizer.EstimationError, match="Prime de risque"):
        optimizer.estimate_expected_returns(mat[["NVDA"]], meta.loc[["NVDA"]], cfg,
                                             benchmark_returns=mat.rename(columns={"SPY": "SMH"})[["SMH"]])


def test_08_capm_benchmark_uses_specific_premium():
    mat, meta = sample_dataset()
    cfg = config.get_base_settings()
    cfg["estimation"]["mode"] = "single_method"
    cfg["estimation"]["single_method"] = "capm_benchmark_shrinkage"
    cfg["estimation"]["capm_benchmark_shrinkage"]["erp_annual_by_benchmark"] = {"SMH": 0.09}
    got = optimizer.estimate_expected_returns(mat[["NVDA"]], meta.loc[["NVDA"]], cfg,
                                              benchmark_returns=mat.rename(columns={"SPY":"SMH"})[["SMH"]])
    assert got.details.loc["NVDA", "benchmark"] == "SMH"
    assert got.annual["NVDA"] == pytest.approx(
        .5 * mat["NVDA"].mean() * 252 + .5 * (.035 + got.details.loc["NVDA", "beta"] * .09))


def test_09_crypto_ewma_default_and_bond_historical():
    mat, meta = sample_dataset()
    cfg = config.get_base_settings()
    got = optimizer.estimate_expected_returns(mat, meta, cfg)
    assert got.details.loc["BTC-CAD", "method"] == "ewma"
    assert got.details.loc["XBB.TO", "method"] == "historical"
    assert got.details.loc["NVDA", "method"] == "capm_shrinkage"


def test_10_beta_needs_paired_observations():
    mat, meta = sample_dataset()
    cfg = config.get_base_settings()
    mat.loc[mat.index[:100], "SPY"] = np.nan
    with pytest.raises(optimizer.EstimationError, match="observations communes"):
        optimizer.estimate_expected_returns(mat[["NVDA"]], meta.loc[["NVDA"]], cfg,
                                             benchmark_returns=mat[["SPY"]])


def test_11_beta_zero_variance_fails():
    mat, meta = sample_dataset()
    cfg = config.get_base_settings()
    zero = pd.DataFrame({"SPY": np.zeros(len(mat))}, index=mat.index)
    with pytest.raises(optimizer.EstimationError, match="variance nulle"):
        optimizer.estimate_expected_returns(mat[["NVDA"]], meta.loc[["NVDA"]], cfg,
                                             benchmark_returns=zero)


def test_12_cov_ledoit_wolf_is_psd():
    mat, _ = sample_dataset()
    est = optimizer.estimate_covariance(mat, cfg_hist())
    assert est.method == "ledoit_wolf"
    assert est.observations == 160
    assert est.min_eigenvalue >= -1e-10
    assert 0 <= est.shrinkage <= 1
    assert np.allclose(est.annual, est.annual.T)


def test_13_cov_only_selected_columns():
    mat, _ = sample_dataset()
    est = optimizer.estimate_covariance(mat, cfg_hist(), symbols=["NVDA", "XBB.TO"])
    assert est.annual.shape == (2,2)
    assert list(est.annual.index) == ["NVDA", "XBB.TO"]


def test_14_cov_ledoit_rejects_missing_joint_data():
    mat, _ = sample_dataset()
    cfg = cfg_hist()
    mat.loc[mat.index[:80], "NVDA"] = np.nan
    mat.loc[mat.index[80:], "AAPL"] = np.nan
    cfg["covariance"]["min_observations_per_asset"] = 75
    with pytest.raises(optimizer.EstimationError, match="dates communes"):
        optimizer.estimate_covariance(mat[["NVDA", "AAPL"]], cfg)


def test_15_cov_sample_is_annualized():
    mat, _ = sample_dataset()
    cfg = cfg_hist()
    cfg["covariance"]["method"] = "sample"
    got = optimizer.estimate_covariance(mat[["NVDA", "AAPL"]], cfg)
    assert got.annual.loc["NVDA", "NVDA"] == pytest.approx(mat["NVDA"].var() * 252)
    assert got.annual.loc["NVDA", "AAPL"] == pytest.approx(mat["NVDA"].cov(mat["AAPL"]) * 252)


def test_16_sample_cov_pairwise_missing_overlap_fails():
    mat, _ = sample_dataset()
    cfg = cfg_hist()
    cfg["covariance"]["method"] = "sample"
    mat.loc[mat.index[:85], "NVDA"] = np.nan
    mat.loc[mat.index[75:], "AAPL"] = np.nan
    cfg["covariance"]["min_observations_per_asset"] = 70
    with pytest.raises(optimizer.EstimationError, match="observations communes"):
        optimizer.estimate_covariance(mat[["NVDA", "AAPL"]], cfg)


def test_17_portfolio_budget_and_nonnegative_weights():
    mat, meta = sample_dataset()
    cfg = cfg_hist()
    p = plan_for(meta, cfg)
    res = optimizer.optimize_weights(
        optimizer.estimate_expected_returns(mat, meta, cfg),
        optimizer.estimate_covariance(mat, cfg), p, cfg)
    assert res.weights.sum() == pytest.approx(1, abs=1e-7)
    assert (res.weights >= -1e-7).all()
    constraints.validate_weights(res.weights, p)


def test_18_cash_guardrail_single_stock_sector_50():
    mat, meta = sample_dataset()
    cfg = cfg_agent_hist({"group_limits":{"sector":{"Information Technology":{"max":0.5}}}})
    meta = meta.loc[["NVDA"]]
    p = plan_for(meta, cfg)
    mu, cov = manual_mu_cov(meta, [0.5], .01)
    res = optimizer.optimize_weights(mu, cov, p, cfg)
    assert res.weights["NVDA"] == pytest.approx(.5, abs=1e-6)
    assert res.weights["CASH-CAD"] == pytest.approx(.5, abs=1e-6)


def test_19_required_stock_and_cash_min():
    mat, meta = sample_dataset()
    cfg = cfg_agent_hist({"required_symbols":["AAPL"], "min_cash_weight":0.2})
    p = plan_for(meta, cfg)
    mu, cov = manual_mu_cov(meta,[.03, .04,.05,.01,.01])
    res = optimizer.optimize_weights(mu, cov, p, cfg)
    assert res.weights["AAPL"] >= .01 -1e-7
    assert res.cash_weight >= .2 -1e-7


def test_20_cash_cannot_bypass_max_cash_limit():
    mat, meta = sample_dataset()
    cfg = cfg_agent_hist({"max_cash_weight":0.3,"group_limits":{"sector":{"Information Technology":{"max":.5}}}})
    meta=meta.loc[["NVDA"]]
    p=plan_for(meta,cfg)
    mu,cov=manual_mu_cov(meta,[.5])
    with pytest.raises(constraints.ConstraintInfeasibleError):
        optimizer.optimize_weights(mu,cov,p,cfg)


def test_21_prune_micro_positions():
    mat, meta = sample_dataset()
    cfg = cfg_hist()
    # Very low expected returns relative to A -> cash optimal, and with these
    # mixed mu values, one tiny allocation may appear; audit must always pass.
    meta=meta.loc[["NVDA","AAPL"]]
    p=plan_for(meta,cfg)
    mu,cov=manual_mu_cov(meta,[.02,.0001],.25)
    res=optimizer.optimize_weights(mu,cov,p,cfg)
    constraints.validate_weights(res.weights,p)
    assert not any(1e-7 < res.weights[s] < .01 - 1e-7 for s in p.risky_symbols)


def test_22_high_risk_aversion_more_cash():
    mat, meta = sample_dataset()
    meta=meta.loc[["NVDA"]]
    c1=cfg_hist();c2=cfg_hist()
    c1["risk_aversion"]["default"] = 1.0
    c2["risk_aversion"]["default"] = 25.0
    p=plan_for(meta,c1)
    mu,cov=manual_mu_cov(meta,[.05], .25)
    x=optimizer.optimize_weights(mu,cov,p,c1)
    y=optimizer.optimize_weights(mu,cov,p,c2)
    assert y.cash_weight >= x.cash_weight


def test_23_forced_required_no_micro_even_when_negative_mu():
    mat, meta = sample_dataset()
    meta=meta.loc[["NVDA"]]
    cfg=cfg_agent_hist({"required_symbols":["NVDA"]})
    p=plan_for(meta,cfg)
    mu,cov=manual_mu_cov(meta,[-.1], .05)
    x=optimizer.optimize_weights(mu,cov,p,cfg)
    assert x.weights["NVDA"] >= .01-1e-7


def test_24_soft_preference_not_silently_ignored():
    mat, meta=sample_dataset()
    cfg=cfg_agent_hist({"preferences":{"sector":{"Information Technology":"more"}}})
    p=plan_for(meta.loc[["NVDA","AAPL"]],cfg)
    mu,cov=manual_mu_cov(meta.loc[["NVDA","AAPL"]],[.1,.2])
    with pytest.raises(constraints.UnresolvedPreferenceError):
        optimizer.optimize_weights(mu,cov,p,cfg)


def test_25_bad_covariance_negative_eigenvalue_rejected():
    mat,meta=sample_dataset()
    meta=meta.loc[["NVDA","AAPL"]]
    cfg=cfg_hist();p=plan_for(meta,cfg)
    mu=pd.Series([.1,.1],index=meta.index)
    cov=pd.DataFrame([[.1,.2],[.2,.1]],index=meta.index,columns=meta.index)
    with pytest.raises(optimizer.OptimizationError,match="positive semi"):
        optimizer.optimize_weights(mu,cov,p,cfg)


def test_26_missing_mu_fails():
    mat,meta=sample_dataset()
    cfg=cfg_hist();p=plan_for(meta,cfg)
    mu,cov=manual_mu_cov(meta,[.1]*len(meta))
    with pytest.raises(optimizer.OptimizationError,match="Rendements absents"):
        optimizer.optimize_weights(mu.drop("NVDA"),cov,p,cfg)


def test_27_future_return_column_refused():
    mat,meta=sample_dataset()
    mat["total_return_cad_fwd_1d"] = 100
    with pytest.raises(optimizer.EstimationError, match="futur"):
        optimizer.estimate_expected_returns(mat,meta,cfg_hist())


def test_28_dates_out_of_order_sorted():
    mat,meta=sample_dataset()
    shuffled=mat.sample(frac=1,random_state=2)
    cfg=cfg_hist()
    a=optimizer.estimate_expected_returns(mat,meta,cfg)
    b=optimizer.estimate_expected_returns(shuffled,meta,cfg)
    pd.testing.assert_series_equal(a.annual,b.annual)


def test_29_duplicate_date_rejected():
    mat,_=sample_dataset()
    mat.index=pd.DatetimeIndex([mat.index[0]]*len(mat))
    with pytest.raises(optimizer.EstimationError,match="Dates dupliquées"):
        optimizer.estimate_covariance(mat,cfg_hist())


def test_30_full_pipeline_synthetic_panel_baseline():
    mat, meta=sample_dataset()
    rows=[]
    for sym in mat:
        row=meta.loc[sym]
        for date, ret in mat[sym].items():
            rows.append({"date":date,"symbol":sym,"total_return_cad":ret,
                         "asset_class":row.asset_class,"instrument_type":row.instrument_type,
                         "country":row.country,"sector":row.sector,"region":row.region,
                         "is_included_universe":True,"theme":row.theme})
    panel=pd.DataFrame(rows)
    cfg=cfg_hist()
    result=optimizer.optimize_portfolio(panel,cfg)
    assert len(result.selection.symbols)==5
    constraints.validate_weights(result.portfolio.weights,result.plan)
    assert result.portfolio.weights.sum()==pytest.approx(1)
    assert "SPY" in result.selection.symbols


def test_31_full_pipeline_agent_config_independent():
    mat, meta=sample_dataset()
    rows=[]
    for sym in mat:
        row=meta.loc[sym]
        for date, ret in mat[sym].items():
            rows.append({"date":date,"symbol":sym,"total_return_cad":ret,
                         "asset_class":row.asset_class,"instrument_type":row.instrument_type,
                         "country":row.country,"sector":row.sector,"is_included_universe":True,"theme":row.theme})
    panel=pd.DataFrame(rows)
    cfg=cfg_agent_hist({"min_cash_weight":.3,"excluded_symbols":["BTC-CAD"]})
    run=optimizer.optimize_portfolio(panel,cfg)
    assert run.portfolio.cash_weight >= .3 - 1e-7
    assert "BTC-CAD" not in run.selection.symbols


def test_32_return_covariance_ordering_preserved():
    mat, meta=sample_dataset()
    cfg=cfg_hist()
    order=["XBB.TO","NVDA","SPY"]
    p=plan_for(meta.loc[order],cfg)
    est=optimizer.estimate_expected_returns(mat[order],meta.loc[order],cfg)
    cov=optimizer.estimate_covariance(mat[order],cfg)
    res=optimizer.optimize_weights(est,cov,p,cfg)
    assert res.weights.index.tolist()==list(p.symbols)  # contraintes normalise ses tickers


def test_33_no_future_leakage_from_asof():
    mat, meta=sample_dataset()
    rows=[]
    for sym in mat:
        row=meta.loc[sym]
        for date, ret in mat[sym].items():
            rows.append({"date":date,"symbol":sym,"total_return_cad":ret,
                         "asset_class":row.asset_class,"instrument_type":row.instrument_type,
                         "country":row.country,"sector":row.sector,"is_included_universe":True})
    panel=pd.DataFrame(rows)
    cfg=cfg_hist()
    cfg["data"]["as_of"]=mat.index[125].strftime("%Y-%m-%d")
    result=optimizer.optimize_portfolio(panel,cfg)
    assert result.covariance.observations==126


def test_34_universe_asof_external_forbidden():
    mat,meta=sample_dataset()
    cfg=cfg_hist()
    cfg["data"]["as_of"]="2025-05-01"
    with pytest.raises(optimizer.OptimizationError,match="fuite temporelle"):
        optimizer.optimize_portfolio(pd.DataFrame({"date":["2025-01-01"],"symbol":["SPY"],
                          "total_return_cad":[.01]}),cfg,universe=meta)


def test_35_missing_benchmark_future_no_automatic_zero_fill():
    mat,meta=sample_dataset()
    cfg=config.get_base_settings()
    benchmark=mat[["SPY"]].copy()
    benchmark.iloc[0:120]=np.nan
    with pytest.raises(optimizer.EstimationError,match="observations communes"):
        optimizer.estimate_expected_returns(mat[["NVDA"]],meta.loc[["NVDA"]],cfg,
                                             benchmark_returns=benchmark)


def test_36_required_budget_and_cash_cap_validation():
    mat,meta=sample_dataset()
    meta=meta.loc[["NVDA","AAPL"]]
    cfg=cfg_agent_hist({"required_symbol_min_weights":{"NVDA":.6,"AAPL":.6}})
    p=plan_for(meta,cfg)
    mu,cov=manual_mu_cov(meta,[.1,.1])
    with pytest.raises(constraints.ConstraintInfeasibleError):
        optimizer.optimize_weights(mu,cov,p,cfg)


def test_37_returns_nan_not_filled_into_history():
    mat,meta=sample_dataset()
    cfg=cfg_hist()
    mat.loc[mat.index[:50],"NVDA"]=np.nan
    with pytest.raises(optimizer.EstimationError,match="110 < 120"):
        optimizer.estimate_expected_returns(mat,meta,cfg)


def test_38_markowitz_analytic_one_asset_plus_cash():
    _, meta = sample_dataset()
    meta = meta.loc[["NVDA"]]
    cfg = cfg_hist()
    cfg["risk_aversion"]["default"] = 5.0
    p = plan_for(meta, cfg)
    mu, cov = manual_mu_cov(meta, [0.1], sigma_value=0.04)
    result = optimizer.optimize_weights(mu, cov, p, cfg)
    # dU/dw = mu - A*sigma^2*w = 0, donc w = .1/(5*.04) = .5.
    assert result.weights["NVDA"] == pytest.approx(0.5, abs=1e-5)
    assert result.cash_weight == pytest.approx(0.5, abs=1e-5)
    assert result.utility == pytest.approx(0.05 - 0.5 * 5 * 0.04 * .25)


def test_39_pairwise_sample_indefinite_matrix_is_repaired():
    cfg = cfg_hist()
    cfg["covariance"]["method"] = "sample"
    rng = np.random.default_rng(101)
    n = 70
    x = rng.normal(0, 0.01, n)
    y = rng.normal(0, 0.01, n)
    z = rng.normal(0, 0.01, n)
    # Paires observées sur des blocs différents : AB=+1, AC=+1, BC=-1,
    # ce qui est généralement incompatible avec une matrice PSD.
    dates = pd.bdate_range("2025-01-01", periods=3*n)
    mat = pd.DataFrame(np.nan, index=dates, columns=["A", "B", "C"])
    mat.loc[dates[:n], ["A", "B"]] = np.column_stack([x, x])
    mat.loc[dates[n:2*n], ["A", "C"]] = np.column_stack([y, y])
    mat.loc[dates[2*n:], ["B", "C"]] = np.column_stack([z, -z])
    got = optimizer.estimate_covariance(mat, cfg)
    assert got.min_eigenvalue >= -1e-9
    assert any("Projection PSD" in warning for warning in got.notices)


def test_40_excluded_spy_still_used_for_capm_benchmark():
    mat, meta = sample_dataset()
    rows = []
    for sym in mat:
        for date, ret in mat[sym].items():
            row = meta.loc[sym]
            rows.append({"date": date, "symbol": sym, "total_return_cad": ret,
                         "asset_class": row.asset_class, "instrument_type": row.instrument_type,
                         "country": row.country, "sector": row.sector,
                         "is_included_universe": True, "theme": row.theme})
    panel = pd.DataFrame(rows)
    cfg = config.get_agent_settings({"risk_aversion_A": 5.0,
                                     "excluded_symbols": ["SPY"]})
    # Pipeline equity = CAPM SPY; SPY doit rester en historique benchmark,
    # mais PAS dans la sélection d'investissement.
    result = optimizer.optimize_portfolio(panel, cfg)
    assert "SPY" not in result.selection.symbols
    assert result.expected_returns.details.loc["NVDA", "benchmark"] == "SPY"
    constraints.validate_weights(result.portfolio.weights, result.plan)


def test_41_forward_column_dropped_in_full_pipeline():
    mat, meta = sample_dataset()
    rows = []
    for sym in mat:
        row = meta.loc[sym]
        for date, ret in mat[sym].items():
            rows.append({"date": date, "symbol": sym, "total_return_cad": ret,
                         "total_return_cad_fwd_1d": 10_000.0,
                         "asset_class": row.asset_class, "instrument_type": row.instrument_type,
                         "country": row.country, "sector": row.sector,
                         "is_included_universe": True, "theme": row.theme})
    cfg = cfg_hist()
    run = optimizer.optimize_portfolio(pd.DataFrame(rows), cfg)
    assert abs(run.portfolio.expected_return_annual) < 1.0


def test_42_required_symbol_conflicts_with_excluded_sector():
    mat, meta = sample_dataset()
    rows = []
    for sym in mat:
        row = meta.loc[sym]
        for date, ret in mat[sym].items():
            rows.append({"date": date, "symbol": sym, "total_return_cad": ret,
                         "asset_class": row.asset_class, "instrument_type": row.instrument_type,
                         "country": row.country, "sector": row.sector,
                         "is_included_universe": True, "theme": row.theme})
    cfg = cfg_agent_hist({"required_symbols": ["NVDA"],
                          "excluded_sectors": ["Information Technology"]})
    with pytest.raises(constraints.ConstraintInfeasibleError, match="requis"):
        optimizer.optimize_portfolio(pd.DataFrame(rows), cfg)
