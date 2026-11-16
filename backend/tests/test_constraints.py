
import copy

import numpy as np
import pandas as pd
import pytest

from invest_agents import config, constraints


def universe_demo():
    """Fidèle à data.build_universe : index symbol, métadonnées et compte obs."""
    rows = [
        # symbol, class, instrument, obs, included, sector, country, region, theme
        ("AAPL", "Equity", "Stock", 1000, True, "Information Technology", "United States", "usa", "tech"),
        ("NVDA", "Equity", "Stock", 1000, True, "Information Technology", "United States", "usa", "ia;tech"),
        ("LMT", "Equity", "Stock", 900, True, "Industrials", "United States", "usa", "armement"),
        ("RY.TO", "Equity", "Stock", 1300, True, "Financials", "Canada", "canada", "finance"),
        ("XBB.TO", "Fixed Income", "ETF", 1300, True, "Non classé", "Non classé", pd.NA, pd.NA),
        ("SPY", "Equity", "ETF", 1250, True, "Non classé", "Non classé", pd.NA, "tech"),
        ("BTC-CAD", "Alternative", "Cryptocurrency", 1200, True, "Non classé", "Non classé", pd.NA, pd.NA),
        ("NEW", "Equity", "Stock", 50, True, "Industrials", "Canada", "canada", pd.NA),
        ("GONE", "Equity", "Stock", 1000, False, "Industrials", "Canada", "canada", pd.NA),
    ]
    return pd.DataFrame(rows, columns=["symbol", "asset_class", "instrument_type", "observations",
                                       "is_included_universe", "sector", "country", "region", "theme"]).set_index("symbol")


def base(**kwargs):
    """Profile V4, avec les settings de la simulation explicitement modifiables."""
    cfg = config.get_base_settings()
    if kwargs:
        cfg = config.apply_portfolio_request({"risk_aversion_A": 5.0, **kwargs}, settings=cfg)
    return cfg


def agent(**kwargs):
    return config.get_agent_settings({"risk_aversion_A": 5.0, **kwargs})


def plan(settings=None, overrides=None):
    cfg = settings or base()
    screened = constraints.filter_eligible_universe(universe_demo(), cfg, exposure_overrides=overrides)
    return constraints.build_constraint_plan(screened.universe, cfg, exposure_overrides=overrides)


def test_01_filter_history_and_investable_flag():
    screened = constraints.filter_eligible_universe(universe_demo(), base())
    assert "NEW" not in screened.symbols and "GONE" not in screened.symbols
    assert "AAPL" in screened.symbols
    assert "short_history:<120" in screened.rejected.set_index("symbol").loc["NEW", "reasons"]


def test_02_base_agent_same_request_same_screening():
    request = {"excluded_symbols": ["NVDA"], "etf_only": False}
    one = constraints.filter_eligible_universe(universe_demo(), base(**request))
    two = constraints.filter_eligible_universe(universe_demo(), agent(**request))
    assert one.symbols == two.symbols


def test_03_excluded_ticker():
    r = constraints.filter_eligible_universe(universe_demo(), agent(excluded_symbols=["nvda"]))
    assert "NVDA" not in r.symbols


def test_04_excluded_theme_multitag():
    r = constraints.filter_eligible_universe(universe_demo(), agent(excluded_themes=["IA"]))
    assert "NVDA" not in r.symbols and "AAPL" in r.symbols


def test_05_etf_only_keeps_only_etfs():
    r = constraints.filter_eligible_universe(universe_demo(), agent(etf_only=True))
    assert r.symbols == ("SPY", "XBB.TO")


def test_06_required_stock_preserved():
    r = constraints.filter_eligible_universe(universe_demo(), agent(required_symbols=["nvda"]))
    assert r.required_symbols == ("NVDA",)


def test_07_required_but_theme_excluded_fails():
    with pytest.raises(constraints.ConstraintInfeasibleError, match="requis"):
        constraints.filter_eligible_universe(universe_demo(), agent(required_symbols=["NVDA"], excluded_themes=["ia"]))


def test_08_required_but_etf_only_fails():
    with pytest.raises(constraints.ConstraintInfeasibleError):
        constraints.filter_eligible_universe(universe_demo(), agent(required_symbols=["AAPL"], etf_only=True))


def test_09_required_but_short_history_fails():
    with pytest.raises(constraints.ConstraintInfeasibleError):
        constraints.filter_eligible_universe(universe_demo(), agent(required_symbols=["NEW"]))


def test_10_required_unknown_symbol_fails():
    with pytest.raises(constraints.ConstraintInfeasibleError, match="absents"):
        constraints.filter_eligible_universe(universe_demo(), agent(required_symbols=["ZZZZ"]))


def test_11_etf_unknown_country_removed_if_country_excluded():
    r = constraints.filter_eligible_universe(universe_demo(), agent(excluded_countries=["Canada"]))
    assert "RY.TO" not in r.symbols
    assert "SPY" not in r.symbols and "XBB.TO" not in r.symbols
    assert "AAPL" in r.symbols


def test_12_verified_lookthrough_can_preserve_etf():
    exposures = {"SPY": {"country": {"United States": 1.0}}}
    r = constraints.filter_eligible_universe(universe_demo(), agent(excluded_countries=["Canada"]),
                                             exposure_overrides=exposures)
    assert "SPY" in r.symbols and "XBB.TO" not in r.symbols


def test_13_partial_lookthrough_not_treated_as_complete():
    exposures = {"SPY": {"country": {"United States": 0.7}}}
    r = constraints.filter_eligible_universe(universe_demo(), agent(excluded_countries=["Canada"]),
                                             exposure_overrides=exposures)
    assert "SPY" not in r.symbols


def test_14_lookthrough_over_100_percent_fails():
    exposures = {"SPY": {"region": {"usa": 0.7, "europe": 0.6}}}
    with pytest.raises(constraints.ConstraintError, match="100"):
        constraints.filter_eligible_universe(universe_demo(), agent(excluded_regions=["canada"]),
                                             exposure_overrides=exposures)


def test_15_theme_tag_is_not_claimed_as_etf_lookthrough():
    r = constraints.filter_eligible_universe(universe_demo(), agent(excluded_themes=["tech"]))
    assert "SPY" not in r.symbols
    assert any("look-through" in w for w in r.warnings)


def test_16_no_inferred_etf_country_without_controls():
    r = constraints.filter_eligible_universe(universe_demo(), base())
    assert "SPY" in r.symbols and "XBB.TO" in r.symbols


def test_17_ticker_preference_exact():
    cfg = agent(preferences={"symbol": {"nvda": {"mode": "exact", "weight": 0.05}}})
    r = constraints.filter_eligible_universe(universe_demo(), cfg)
    assert "NVDA" in r.required_symbols
    p = constraints.build_constraint_plan(r.universe, cfg)
    i = p.index_of("NVDA")
    assert p.lower_bounds[i] == pytest.approx(0.05) and p.upper_bounds[i] == pytest.approx(0.05)


def test_18_preference_exclude_group():
    r = constraints.filter_eligible_universe(universe_demo(), agent(preferences={"theme": {"armement": "exclude"}}))
    assert "LMT" not in r.symbols


def test_19_exact_without_amount_refused():
    with pytest.raises(ValueError, match="exige un poids"):
        agent(preferences={"theme": {"ia": {"mode": "exact"}}})


def test_20_theme_exact_is_a_share_of_the_equity_sleeve():
    cfg = agent(preferences={"theme": {"tech": {"mode": "exact", "weight": 0.1}}})
    r = constraints.filter_eligible_universe(universe_demo(), cfg)
    p = constraints.build_constraint_plan(r.universe, cfg)
    g = next(g for g in p.groups if g.name == "pref_exact:theme:tech")
    assert g.minimum == 0.0 and g.maximum == 0.0  # (e_tech − 0,1 × equity) @ w = 0
    assert g.coefficients[p.index_of("NVDA")] == pytest.approx(0.9)
    assert g.coefficients[p.index_of("SPY")] == pytest.approx(-0.1)  # FNB tagué tech: poche, jamais groupe
    assert g.coefficients[p.index_of("XBB.TO")] == 0.0


def test_21_group_bound_sector_and_cash():
    cfg = agent(group_limits={"sector": {"Information Technology": {"max": 0.2}}}, min_cash_weight=0.1)
    r = constraints.filter_eligible_universe(universe_demo(), cfg)
    p = constraints.build_constraint_plan(r.universe, cfg)
    assert "SPY" not in r.symbols  # ETF sans secteur vérifié
    assert p.lower_bounds[-1] == pytest.approx(0.1)
    constraint = next(g for g in p.groups if g.name == "sector:information technology")
    assert constraint.coefficients[p.index_of("AAPL")] == 1
    assert constraint.coefficients[p.index_of("RY.TO")] == 0


def test_22_theme_overlap_no_double_counting():
    cfg = agent(group_limits={"theme": {"ia": {"min": 0.4}, "tech": {"min": 0.4}}})
    r = constraints.filter_eligible_universe(universe_demo(), cfg)
    p = constraints.build_constraint_plan(r.universe, cfg)
    weights = dict.fromkeys(p.symbols, 0.0)
    weights["NVDA"] = 0.4
    weights["RY.TO"] = 0.6
    constraints.validate_weights(weights, p)


def test_23_default_cash_is_synthetic():
    p = plan()
    assert p.symbols[-1] == "CASH-CAD"
    assert "CASH-CAD" not in p.risky_symbols
    assert p.upper_bounds[-1] == 1.0


def test_24_cash_only_valid_if_maximum_allows():
    p = plan()
    w = dict.fromkeys(p.symbols, 0.0)
    w["CASH-CAD"] = 1.0
    constraints.validate_weights(w, p)


def test_25_required_symbol_at_least_one_percent():
    p = plan(agent(required_symbols=["AAPL"]))
    assert p.lower_bounds[p.index_of("AAPL")] == pytest.approx(0.01)


def test_26_explicit_required_floor():
    p = plan(agent(required_symbol_min_weights={"AAPL": 0.15}))
    assert p.lower_bounds[p.index_of("AAPL")] == pytest.approx(0.15)


def test_27_cap_less_than_required_min_fails():
    cfg = agent(max_weight_per_asset=0.10, required_symbol_min_weights={"AAPL": 0.20})
    r = constraints.filter_eligible_universe(universe_demo(), cfg)
    with pytest.raises(constraints.ConstraintInfeasibleError):
        constraints.build_constraint_plan(r.universe, cfg)


def test_28_minimum_holding_disjunction_detects_micro_weight():
    p = plan()
    w = dict.fromkeys(p.symbols, 0.0)
    w["AAPL"] = 0.005
    w["CASH-CAD"] = 0.995
    with pytest.raises(constraints.ConstraintInfeasibleError, match="1 %"):
        constraints.validate_weights(w, p)
    constraints.validate_weights(w, p, enforce_minimum_holding=False)


def test_29_sum_of_weights_must_be_one():
    p = plan()
    with pytest.raises(constraints.ConstraintInfeasibleError, match="Somme"):
        constraints.validate_weights(np.zeros(len(p.symbols)), p)


def test_30_negative_weight_rejected():
    p = plan()
    w = dict.fromkeys(p.symbols, 0.0)
    w["AAPL"] = -0.1
    w["CASH-CAD"] = 1.1
    with pytest.raises(constraints.ConstraintInfeasibleError):
        constraints.validate_weights(w, p)


def test_31_group_cap_enforced_after_solver():
    cfg = agent(group_limits={"asset_class": {"Equity": {"max": 0.4}}})
    p = plan(cfg)
    w = dict.fromkeys(p.symbols, 0.0)
    w["AAPL"] = 0.5
    w["CASH-CAD"] = 0.5
    with pytest.raises(constraints.ConstraintInfeasibleError, match="Groupe"):
        constraints.validate_weights(w, p)


def test_32_linear_feasibility_detects_disjoint_minima():
    cfg = agent(group_limits={"asset_class": {"Equity": {"min": 0.8}, "Fixed Income": {"min": 0.8}}})
    p = plan(cfg)
    with pytest.raises(constraints.ConstraintInfeasibleError, match="incompatibles"):
        constraints.check_linear_feasibility(p)


def test_33_linear_feasibility_success():
    cfg = agent(group_limits={"asset_class": {"Equity": {"min": 0.2}}}, min_cash_weight=0.1)
    constraints.check_linear_feasibility(plan(cfg))


def test_34_bounded_scipy_constraints():
    cfg = agent(group_limits={"asset_class": {"Fixed Income": {"max": 0.3}}})
    p = plan(cfg)
    bounds, linear = constraints.scipy_constraints(p)
    assert len(linear) == 2
    assert np.isclose(bounds.lb[-1], 0.0)
    assert np.isclose(linear[0].lb, 1.0)


@pytest.mark.parametrize("level", ["less", "more", "require"])
def test_35_legacy_levels_are_refused_not_silently_ignored(level):
    with pytest.raises(ValueError, match="inconnu"):
        agent(preferences={"theme": {"ia": level}})


def test_36_base_has_no_unresolved_soft_preference():
    constraints.assert_ready_for_optimization(plan(base()))


def test_37_no_global_config_mutation():
    original = copy.deepcopy(config.get_base_settings())
    cfg = agent(excluded_symbols=["NVDA"])
    _ = constraints.filter_eligible_universe(universe_demo(), cfg)
    assert config.get_base_settings() == original


def test_38_candidate_selection_respects_max_and_required():
    rows = []
    for n in range(75):
        rows.append({"symbol": f"STOCK{n}", "asset_class": "Equity", "instrument_type": "Stock",
                     "observations": 800, "is_included_universe": True, "sector": "Financials",
                     "country": "Canada", "region": "canada", "theme": ""})
    univ = pd.DataFrame(rows).set_index("symbol")
    cfg = agent(required_symbols=["STOCK74"])
    r = constraints.filter_eligible_universe(univ, cfg)
    selection = constraints.select_candidates(r, cfg)
    assert len(selection.symbols) == 50
    assert "STOCK74" in selection.symbols


def test_39_candidate_selection_does_not_need_covariance():
    cfg = base()
    r = constraints.filter_eligible_universe(universe_demo(), cfg)
    selected = constraints.select_candidates(r, cfg)
    assert len(selected.symbols) == len(r.symbols)
    assert any("Corrélations" in w for w in selected.warnings)


def test_40_correlation_deduplication_when_returns_provided():
    cfg = base()
    cfg["candidates"].update({"target_count": 2, "min_count": 1, "max_count": 3})
    raw = universe_demo().loc[["AAPL", "NVDA", "RY.TO"]].copy()
    r = constraints.filter_eligible_universe(raw, cfg)
    x = np.sin(np.arange(500) / 6)
    rets = pd.DataFrame({"AAPL": x, "NVDA": x, "RY.TO": np.cos(np.arange(500) / 3)})
    result = constraints.select_candidates(r, cfg, returns=rets)
    assert not ({"AAPL", "NVDA"} <= set(result.symbols))


def test_41_invalid_duplicate_tickers():
    raw = universe_demo()
    raw = pd.concat([raw, raw.iloc[[0]]])
    with pytest.raises(constraints.ConstraintError, match="une seule"):
        constraints.filter_eligible_universe(raw, base())


def test_42_missing_observations_column():
    raw = universe_demo().drop(columns=["observations"])
    with pytest.raises(constraints.ConstraintError, match="observations"):
        constraints.filter_eligible_universe(raw, base())


def test_43_reject_investor_group_factor_without_metadata():
    with pytest.raises(constraints.ConstraintInfeasibleError):
        constraints.filter_eligible_universe(universe_demo(), agent(excluded_factors=["value"]))


def test_44_cash_nonzero_with_etf_only():
    cfg = agent(etf_only=True, min_cash_weight=0.2)
    p = plan(cfg)
    w = dict.fromkeys(p.symbols, 0.0)
    w["SPY"] = 0.8
    w["CASH-CAD"] = 0.2
    constraints.validate_weights(w, p)


def test_45_summarize_plan_json_ready():
    p = plan(agent(required_symbols=["NVDA"]))
    out = constraints.summarize_plan(p)
    assert out["cash_symbol"] == "CASH-CAD"
    assert out["required_symbols"] == ["NVDA"]
    assert out["minimum_holding_requires_post_processing"] is True


def test_46_pipeline_with_actual_data_module_on_synthetic_panel():
    """Import réel data.py → build_universe → screening → returns de candidats."""
    from invest_agents import data

    rows = []
    for day in ("2026-11-10", "2026-11-11", "2026-11-12"):
        rows.extend([
            {"date": day, "symbol": "AAPL", "total_return_cad": 0.01,
             "close_price_cad": 100.0, "asset_class": "Equity", "instrument_type": "Stock",
             "is_included_universe": True, "sector": "Information Technology", "country": "United States"},
            {"date": day, "symbol": "XBB.TO", "total_return_cad": 0.001,
             "close_price_cad": 25.0, "asset_class": "Fixed Income", "instrument_type": "ETF",
             "is_included_universe": True, "sector": "Non classé", "country": "Non classé"},
        ])
    panel = data.normalize_market_data(pd.DataFrame(rows))
    universe = data.build_universe(panel)
    cfg = config.get_base_settings()
    cfg["data"]["min_observations"] = 2  # uniquement pour ce test synthétique
    screened = constraints.filter_eligible_universe(universe, cfg)
    selected = constraints.select_candidates(screened, cfg)
    returns = data.build_returns_matrix(panel, selected.symbols)
    assert set(returns.columns) == {"AAPL", "XBB.TO"}
    assert returns.shape == (3, 2)


def test_47_feasibility_expands_candidate_count_when_needed():
    rows = [{"symbol": f"E{i:02d}", "asset_class": "Equity", "instrument_type": "Stock",
             "observations": 800, "is_included_universe": True,
             "sector": "Financials", "country": "Canada", "region": "canada", "theme": ""}
            for i in range(15)]
    univ = pd.DataFrame(rows).set_index("symbol")
    cfg = agent(max_weight_per_asset=0.1,
                group_limits={"asset_class": {"Equity": {"min": 0.8}}},
                max_cash_weight=0.2)
    cfg["candidates"].update({"target_count": 3, "min_count": 1, "max_count": 12})
    r = constraints.filter_eligible_universe(univ, cfg)
    selected = constraints.select_candidates(r, cfg)
    assert len(selected.symbols) >= 8
    assert len(selected.symbols) <= 12
    p = constraints.build_constraint_plan(selected, cfg)
    constraints.check_linear_feasibility(p)


def test_48_fails_when_candidate_limit_makes_allocation_impossible():
    rows = [{"symbol": f"E{i:02d}", "asset_class": "Equity", "instrument_type": "Stock",
             "observations": 800, "is_included_universe": True,
             "sector": "Financials", "country": "Canada", "region": "canada", "theme": ""}
            for i in range(15)]
    cfg = agent(max_weight_per_asset=0.1,
                group_limits={"asset_class": {"Equity": {"min": 0.8}}},
                max_cash_weight=0.2)
    cfg["candidates"].update({"target_count": 3, "min_count": 1, "max_count": 6})
    r = constraints.filter_eligible_universe(pd.DataFrame(rows).set_index("symbol"), cfg)
    with pytest.raises(constraints.ConstraintInfeasibleError, match="max_count"):
        constraints.select_candidates(r, cfg)


def test_49_empty_manual_factor_map_is_not_verification():
    cfg = agent(excluded_factors=["value"])
    with pytest.raises(constraints.ConstraintError, match="vide"):
        constraints.filter_eligible_universe(universe_demo(), cfg, exposure_overrides={
            "SPY": {"factor": {}}
        })
