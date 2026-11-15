"""Tests de BASE_CONSTRAINTS (config.py) et de leur effet sur constraints.py / optimizer.py.

Vérifie : source unique des contraintes BASE, plafonds agrégés (10 % par titre, 5 % crypto,
15 % marchés émergents, secteurs, classes), traitement des ETF sans look-through, absence de
double comptage crypto / ETP, usage du cash et, surtout, ABSENCE DE CONTAMINATION du mode AGENT.

Les tests « real_ » lisent les métadonnées du vrai Parquet (config.get_parquet_source()) ;
si le fichier est introuvable ils ÉCHOUENT (ils ne sont jamais ignorés).

Lancer depuis backend :
    PYTHONPATH=src python -m pytest -v tests/test_base_constraints.py
"""
from __future__ import annotations

import copy
import gc
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from invest_agents import config, constraints, data, optimizer

CASH = "CASH-CAD"
TOL = 1e-6


# ---------------------------------------------------------------------------
# Univers synthétique, avec la nomenclature réelle du Parquet
# ---------------------------------------------------------------------------
def _universe() -> pd.DataFrame:
    rows: list[tuple] = []

    def stock(symbol, sector, country, region):
        rows.append((symbol, "Equity", "Stock", sector, country, region))

    for s in ("ITA", "ITB", "ITC", "ITD"):
        stock(s, "Information Technology", "United States", "usa")
    for s in ("FNA", "FNB", "FNC", "FND"):
        stock(s, "Financials", "United States", "usa")
    for s in ("ENA", "ENB", "ENC"):
        stock(s, "Energy", "Canada", "canada")
    for s in ("EMA", "EMB"):  # actions émergentes : AUCUNE n'existe dans le vrai Parquet
        stock(s, "Industrials", "Brazil", "emergents")
    stock("UTL", "Utilities", "United States", "usa")
    # ETF : secteur / pays / région « Non classé » (pas de look-through dans le Parquet)
    for s in ("XLK", "EEM"):
        rows.append((s, "Equity", "ETF", "Non classé", "Non classé", None))
    rows.append(("XBB.TO", "Fixed Income", "ETF", "Non classé", "Non classé", None))
    for s in ("GLD", "SLV"):
        rows.append((s, "Commodities", "ETF", "Non classé", "Non classé", None))
    for s in ("RIT", "RIU"):
        rows.append((s, "Real Estate", "ETF", "Non classé", "Non classé", None))
    rows.append(("BITW", "Alternative", "ETF", "Non classé", "Non classé", None))  # ETP crypto
    for s in ("BTC-CAD", "ETH-CAD"):  # crypto directe
        rows.append((s, "Alternative", "Cryptocurrency", "Non classé", "Non classé", None))
    df = pd.DataFrame(rows, columns=["symbol", "asset_class", "instrument_type", "sector", "country", "region"])
    df["observations"] = 200
    df["is_included_universe"] = True
    return df.set_index("symbol")


def _plan(cfg, universe=None, overrides=None):
    universe = _universe() if universe is None else universe
    screened = constraints.filter_eligible_universe(universe, cfg, exposure_overrides=overrides)
    return constraints.build_constraint_plan(screened.universe, cfg, exposure_overrides=overrides)


def hold(plan, holdings):
    """Poids complets : les positions données, le reste en cash (somme = 100 %)."""
    weights = {s: 0.0 for s in plan.symbols}
    weights.update(holdings)
    weights[plan.cash_symbol] = 1.0 - sum(holdings.values())
    return weights


def group(plan, name):
    return next(g for g in plan.groups if g.name == name)


def coefficient(plan, name, symbol):
    return float(group(plan, name).coefficients[plan.symbols.index(symbol)])


def rejected(plan, holdings, match):
    with pytest.raises(constraints.ConstraintInfeasibleError, match=match):
        constraints.validate_weights(hold(plan, holdings), plan)


@pytest.fixture
def base_cfg():
    return config.get_base_settings()


@pytest.fixture
def agent_cfg():
    return config.get_agent_settings({"risk_aversion_A": 5.0})


# ---------------------------------------------------------------------------
# 1. BASE_CONSTRAINTS est la source unique du mode BASE
# ---------------------------------------------------------------------------
def test_base_mode_constraints_are_exactly_base_constraints(base_cfg):
    assert base_cfg["constraints"] == config.BASE_CONSTRAINTS
    assert base_cfg["execution_mode"] == "base"


def test_base_constraints_values_requested(base_cfg):
    c = base_cfg["constraints"]
    assert c["max_weight_per_asset"] == 0.10
    assert c["min_held_weight"] == 0.01
    assert c["min_cash_weight"] == 0.0 and c["max_cash_weight"] == 1.0
    limits = c["group_limits"]
    assert limits["instrument_type"] == {"Cryptocurrency": {"max": 0.05}}
    assert limits["asset_class"] == {
        "Alternative": {"max": 0.05}, "Commodities": {"max": 0.10}, "Real Estate": {"max": 0.15}}
    assert limits["sector"] == {
        "Information Technology": {"max": 0.25}, "Financials": {"max": 0.30}, "Energy": {"max": 0.20}}
    assert limits["region"] == {"emergents": {"max": 0.15}}
    assert limits["country"] == limits["theme"] == limits["factor"] == {}
    assert c["unknown_exposure_policy"] == "flag"


def test_base_constraints_cover_every_constraints_key():
    assert set(config.CONSTRAINTS) <= set(config.BASE_CONSTRAINTS)
    assert set(config.BASE_CONSTRAINTS) - set(config.CONSTRAINTS) == {"unknown_exposure_policy"}


def test_base_profile_has_no_duplicated_constraint_field():
    assert set(config.BASE_PROFILE) <= config.BASE_PROFILE_ALLOWED_KEYS
    assert not set(config.BASE_PROFILE) & set(config.BASE_CONSTRAINTS)


def test_editing_base_constraints_is_the_only_place_to_change_simulation_limits(monkeypatch):
    edited = copy.deepcopy(config.BASE_CONSTRAINTS)
    edited["max_weight_per_asset"] = 0.07
    edited["min_cash_weight"] = 0.20
    edited["group_limits"]["sector"]["Energy"] = {"max": 0.01}
    monkeypatch.setattr(config, "BASE_CONSTRAINTS", edited)
    c = config.get_base_settings()["constraints"]
    assert c["max_weight_per_asset"] == 0.07
    assert c["min_cash_weight"] == 0.20
    assert c["group_limits"]["sector"]["Energy"] == {"max": 0.01}


def test_duplicated_constraint_in_base_profile_is_rejected(monkeypatch):
    monkeypatch.setattr(config, "BASE_PROFILE", {**config.BASE_PROFILE, "max_weight_per_asset": 0.5})
    with pytest.raises(ValueError, match="BASE_PROFILE"):
        config.get_base_settings()


def test_missing_or_unknown_key_in_base_constraints_is_rejected(monkeypatch):
    missing = {k: v for k, v in config.BASE_CONSTRAINTS.items() if k != "excluded_symbols"}
    monkeypatch.setattr(config, "BASE_CONSTRAINTS", missing)
    with pytest.raises(ValueError, match="incomplet"):
        config.get_base_settings()
    monkeypatch.setattr(config, "BASE_CONSTRAINTS", {**config.BASE_CONSTRAINTS, "max_weight_per_asste": 0.1})
    with pytest.raises(ValueError):
        config.get_base_settings()


@pytest.mark.parametrize("dimension, name", [("asset_class", "Alternatif"), ("instrument_type", "Crypto")])
def test_nonexistent_group_name_is_rejected(monkeypatch, dimension, name):
    edited = copy.deepcopy(config.BASE_CONSTRAINTS)
    edited["group_limits"][dimension] = {name: {"max": 0.05}}
    monkeypatch.setattr(config, "BASE_CONSTRAINTS", edited)
    with pytest.raises(ValueError, match="inexistants"):
        config.get_base_settings()


@pytest.mark.parametrize("bounds", [{"max": 1.5}, {"min": 0.3, "max": 0.1}, {"maximum": 0.1}, {}])
def test_invalid_group_bounds_in_base_constraints_are_rejected(monkeypatch, bounds):
    edited = copy.deepcopy(config.BASE_CONSTRAINTS)
    edited["group_limits"]["sector"]["Energy"] = bounds
    monkeypatch.setattr(config, "BASE_CONSTRAINTS", edited)
    with pytest.raises(ValueError):
        config.get_base_settings()


def test_invalid_unknown_exposure_policy_is_rejected(monkeypatch):
    monkeypatch.setattr(config, "BASE_CONSTRAINTS", {**config.BASE_CONSTRAINTS, "unknown_exposure_policy": "ignore"})
    with pytest.raises(ValueError, match="unknown_exposure_policy"):
        config.get_base_settings()


# ---------------------------------------------------------------------------
# 2. CONTAMINATION : le mode AGENT n'est jamais touché par les limites BASE
# ---------------------------------------------------------------------------
def test_agent_constraints_are_exactly_the_original_constraints(agent_cfg):
    assert agent_cfg["constraints"] == config.CONSTRAINTS
    assert agent_cfg["execution_mode"] == "agent"


def test_agent_has_none_of_the_base_limits(agent_cfg):
    c = agent_cfg["constraints"]
    assert c["max_weight_per_asset"] is None
    assert all(not groups for groups in c["group_limits"].values())
    assert "unknown_exposure_policy" not in c
    assert c["max_weight_by_instrument_type"] == {} and c["max_weight_by_asset_class"] == {}


def test_agent_request_only_changes_what_it_asks(agent_cfg):
    cfg = config.get_agent_settings({"risk_aversion_A": 9.0, "min_cash_weight": 0.10})
    expected = copy.deepcopy(config.CONSTRAINTS)
    expected["min_cash_weight"] = 0.10
    assert cfg["constraints"] == expected
    assert cfg["constraints"]["max_weight_per_asset"] is None


def test_agent_group_limits_come_only_from_the_request():
    cfg = config.get_agent_settings({
        "risk_aversion_A": 5.0, "group_limits": {"sector": {"Information Technology": {"max": 0.40}}}})
    limits = cfg["constraints"]["group_limits"]
    assert limits["sector"] == {"Information Technology": {"max": 0.40}}  # pas 0,25 : valeur de la requête
    assert limits["region"] == limits["instrument_type"] == limits["asset_class"] == {}
    assert cfg["constraints"]["max_weight_per_asset"] is None


def test_changing_base_constraints_never_changes_agent(monkeypatch):
    before = config.get_agent_settings({"risk_aversion_A": 5.0})
    edited = copy.deepcopy(config.BASE_CONSTRAINTS)
    edited["max_weight_per_asset"] = 0.02
    edited["min_cash_weight"] = 0.5
    edited["group_limits"]["sector"]["Energy"] = {"max": 0.0}
    monkeypatch.setattr(config, "BASE_CONSTRAINTS", edited)
    assert config.get_agent_settings({"risk_aversion_A": 5.0}) == before
    assert config.get_base_settings()["constraints"]["max_weight_per_asset"] == 0.02


def test_mutating_returned_settings_never_leaks_across_modes_or_into_globals():
    base_before = copy.deepcopy(config.BASE_CONSTRAINTS)
    agent_before = copy.deepcopy(config.CONSTRAINTS)
    base = config.get_base_settings()
    base["constraints"]["group_limits"]["sector"]["Energy"]["max"] = 0.99
    base["constraints"]["max_weight_per_asset"] = 0.99
    base["constraints"]["excluded_symbols"].append("AAPL")
    agent = config.get_agent_settings({"risk_aversion_A": 5.0})
    agent["constraints"]["group_limits"]["region"]["usa"] = {"max": 0.01}
    agent["constraints"]["excluded_symbols"].append("MSFT")
    assert config.BASE_CONSTRAINTS == base_before
    assert config.CONSTRAINTS == agent_before
    assert config.get_base_settings()["constraints"] == base_before
    assert config.get_agent_settings({"risk_aversion_A": 5.0})["constraints"] == agent_before


def test_call_order_does_not_matter():
    first_agent = config.get_agent_settings({"risk_aversion_A": 5.0})
    base = config.get_base_settings()
    second_agent = config.get_agent_settings({"risk_aversion_A": 5.0})
    assert first_agent == second_agent
    assert config.get_base_settings() == base


def test_agent_plan_has_no_base_cap_and_no_group(agent_cfg):
    plan = _plan(agent_cfg)
    risky = len(plan.risky_symbols)
    assert np.allclose(plan.upper_bounds[:risky], 1.0)  # ni plafond 10 %
    assert plan.groups == ()                            # ni plafonds agrégés
    assert plan.unknown_exposures == {} and plan.inert_groups == ()
    constraints.validate_weights(hold(plan, {"ITA": 0.50, "FNA": 0.50}), plan)  # 50 % dans un titre : permis


def test_same_portfolio_is_valid_for_agent_and_refused_for_base(base_cfg, agent_cfg):
    holdings = {"ITA": 0.50, "BTC-CAD": 0.20, "FNA": 0.30}
    constraints.validate_weights(hold(_plan(agent_cfg), holdings), _plan(agent_cfg))
    with pytest.raises(constraints.ConstraintInfeasibleError):
        constraints.validate_weights(hold(_plan(base_cfg), holdings), _plan(base_cfg))


def test_agent_keeps_strict_policy_and_rejects_unknown_etf_exposure():
    cfg = config.get_agent_settings({
        "risk_aversion_A": 5.0, "group_limits": {"sector": {"Information Technology": {"max": 0.25}}}})
    screened = constraints.filter_eligible_universe(_universe(), cfg)
    kept = set(screened.universe.index)
    assert not kept & {"XLK", "EEM", "XBB.TO", "GLD", "BITW", "BTC-CAD", "ETH-CAD"}  # strict : inconnus rejetés
    assert set(screened.rejected["symbol"]) >= {"XLK", "BITW", "BTC-CAD"}
    assert all("unknown_sector_exposure" in reasons for reasons in screened.rejected["reasons"])


def test_base_with_same_sector_cap_keeps_etfs_and_crypto(base_cfg):
    screened = constraints.filter_eligible_universe(_universe(), base_cfg)
    assert screened.rejected.empty
    assert {"XLK", "EEM", "XBB.TO", "BITW", "BTC-CAD"} <= set(screened.universe.index)


# ---------------------------------------------------------------------------
# 3. Plafond de 10 % par actif ; cash
# ---------------------------------------------------------------------------
def test_each_risky_asset_is_capped_at_10_percent_and_cash_is_not(base_cfg):
    plan = _plan(base_cfg)
    risky = len(plan.risky_symbols)
    assert np.allclose(plan.upper_bounds[:risky], 0.10)
    assert plan.upper_bounds[-1] == 1.0 and plan.cash_symbol == CASH


@pytest.mark.parametrize("symbol", ["ITA", "XLK", "BTC-CAD", "XBB.TO", "GLD"])
def test_single_asset_above_10_percent_is_rejected_stock_etf_or_crypto(base_cfg, symbol):
    plan = _plan(base_cfg)
    constraints.validate_weights(hold(plan, {symbol: 0.04}), plan)
    rejected(plan, {symbol: 0.12}, "hors bornes")


def test_exactly_10_percent_is_accepted(base_cfg):
    plan = _plan(base_cfg)
    constraints.validate_weights(hold(plan, {"XBB.TO": 0.10, "FNA": 0.10, "UTL": 0.10}), plan)


def test_cash_can_hold_100_percent(base_cfg):
    plan = _plan(base_cfg)
    constraints.validate_weights(hold(plan, {}), plan)


def test_cash_is_not_limited_by_the_10_percent_cap(base_cfg):
    plan = _plan(base_cfg)
    constraints.validate_weights(hold(plan, {"UTL": 0.10}), plan)  # cash = 90 %


def test_cash_maximum_still_enforced_when_lowered(base_cfg):
    cfg = copy.deepcopy(base_cfg)
    cfg["constraints"]["max_cash_weight"] = 0.30
    plan = _plan(cfg)
    rejected(plan, {"UTL": 0.10}, "hors bornes")  # cash 90 % > 30 %


# ---------------------------------------------------------------------------
# 4. Crypto : 5 %, directe et ETP, sans double comptage
# ---------------------------------------------------------------------------
def test_crypto_direct_cap_is_5_percent(base_cfg):
    plan = _plan(base_cfg)
    constraints.validate_weights(hold(plan, {"BTC-CAD": 0.05}), plan)
    rejected(plan, {"BTC-CAD": 0.06}, "Groupe")
    rejected(plan, {"BTC-CAD": 0.03, "ETH-CAD": 0.03}, "Groupe")  # BTC + ETH combinés


def test_etp_alone_up_to_5_percent_ok_above_rejected(base_cfg):
    plan = _plan(base_cfg)
    constraints.validate_weights(hold(plan, {"BITW": 0.05}), plan)
    rejected(plan, {"BITW": 0.06}, "asset_class:alternative")


def test_direct_crypto_and_etp_share_one_5_percent_budget(base_cfg):
    """BTC 3 % + BITW 3 % = 6 % de crypto : refusé, bien que chaque ligne soit < 5 %."""
    plan = _plan(base_cfg)
    rejected(plan, {"BTC-CAD": 0.03, "BITW": 0.03}, "asset_class:alternative")
    constraints.validate_weights(hold(plan, {"BTC-CAD": 0.03, "BITW": 0.02}), plan)  # total 5 %
    rejected(plan, {"BTC-CAD": 0.05, "BITW": 0.01}, "asset_class:alternative")


def test_bitw_counted_once_only_in_alternative_not_in_cryptocurrency(base_cfg):
    plan = _plan(base_cfg)
    assert coefficient(plan, "asset_class:alternative", "BITW") == 1.0
    assert coefficient(plan, "instrument_type:cryptocurrency", "BITW") == 0.0
    for symbol in ("BTC-CAD", "ETH-CAD"):
        assert coefficient(plan, "asset_class:alternative", symbol) == 1.0
        assert coefficient(plan, "instrument_type:cryptocurrency", symbol) == 1.0
    # Les deux plafonds sont des inégalités séparées (jamais additionnées : pas de 5 % + 5 %).
    assert group(plan, "asset_class:alternative").maximum == group(plan, "instrument_type:cryptocurrency").maximum == 0.05
    assert group(plan, "asset_class:alternative").coefficients.max() == 1.0


def test_no_other_instrument_is_in_the_crypto_groups(base_cfg):
    plan = _plan(base_cfg)
    in_alternative = {s for s, c in zip(plan.symbols, group(plan, "asset_class:alternative").coefficients) if c > 0}
    in_direct = {s for s, c in zip(plan.symbols, group(plan, "instrument_type:cryptocurrency").coefficients) if c > 0}
    assert in_alternative == {"BTC-CAD", "ETH-CAD", "BITW"}
    assert in_direct == {"BTC-CAD", "ETH-CAD"}


# ---------------------------------------------------------------------------
# 5. Secteurs : plafonds sur expositions CONNUES, ETF signalés et non comptés
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ok, too_much, label", [
    ({"ITA": 0.10, "ITB": 0.10, "ITC": 0.05}, {"ITA": 0.10, "ITB": 0.10, "ITC": 0.06}, "information technology"),
    ({"FNA": 0.10, "FNB": 0.10, "FNC": 0.10}, {"FNA": 0.10, "FNB": 0.10, "FNC": 0.10, "FND": 0.01}, "financials"),
    ({"ENA": 0.10, "ENB": 0.10}, {"ENA": 0.10, "ENB": 0.10, "ENC": 0.02}, "energy"),
])
def test_sector_caps_apply_to_known_stock_exposures(base_cfg, ok, too_much, label):
    plan = _plan(base_cfg)
    constraints.validate_weights(hold(plan, ok), plan)
    rejected(plan, too_much, f"sector:{label}")


def test_sector_cap_does_not_control_etf_underlying_exposure_and_says_so(base_cfg):
    plan = _plan(base_cfg)
    assert coefficient(plan, "sector:information technology", "XLK") == 0.0  # XLK n'est PAS compté
    holdings = {"ITA": 0.10, "ITB": 0.10, "ITC": 0.05, "XLK": 0.10}
    constraints.validate_weights(hold(plan, holdings), plan)  # accepté : exposition réelle inconnue
    unknown = constraints.unknown_exposure_weights(hold(plan, holdings), plan)
    assert unknown["sector"] == pytest.approx(0.10)       # le poids non contrôlé est rapporté
    assert unknown["region"] == pytest.approx(0.10)


def test_unknown_exposures_are_listed_and_notified_in_the_plan(base_cfg):
    plan = _plan(base_cfg)
    etf_and_crypto = {"XLK", "EEM", "XBB.TO", "GLD", "SLV", "RIT", "RIU", "BITW", "BTC-CAD", "ETH-CAD"}
    assert set(plan.unknown_exposures["sector"]) == etf_and_crypto
    assert set(plan.unknown_exposures["region"]) == etf_and_crypto
    assert any("appliqués aux expositions CONNUES" in n and "sector" in n for n in plan.notices)
    summary = constraints.summarize_plan(plan)
    json.dumps(summary)
    assert set(summary["unknown_exposures"]["sector"]) == etf_and_crypto


def test_stock_with_missing_region_is_flagged_not_dropped(base_cfg):
    universe = _universe()
    universe.loc["UTL", "region"] = None
    plan = _plan(base_cfg, universe)
    assert "UTL" in plan.unknown_exposures["region"]
    assert "UTL" in plan.risky_symbols
    assert "UTL" not in plan.unknown_exposures["sector"]  # son secteur, lui, est connu


# ---------------------------------------------------------------------------
# 6. Marchés émergents : 15 %, nom réel « emergents »
# ---------------------------------------------------------------------------
def test_emerging_markets_cap_15_percent_on_known_stocks(base_cfg):
    plan = _plan(base_cfg)
    assert "region:emergents" in {g.name for g in plan.groups}
    assert plan.inert_groups == ()                       # il y a des actions émergentes ici
    constraints.validate_weights(hold(plan, {"EMA": 0.08, "EMB": 0.07}), plan)  # 15 %
    rejected(plan, {"EMA": 0.08, "EMB": 0.08}, "region:emergents")              # 16 %


def test_emerging_cap_is_inert_and_flagged_when_nothing_is_exposed(base_cfg):
    universe = _universe().drop(index=["EMA", "EMB"])    # situation du vrai Parquet
    plan = _plan(base_cfg, universe)
    assert plan.inert_groups == ("region:emergents",)
    assert any("INERTE" in n and "region:emergents" in n for n in plan.notices)


def test_misspelled_region_name_is_reported_inert(base_cfg):
    cfg = copy.deepcopy(base_cfg)
    cfg["constraints"]["group_limits"]["region"] = {"Emerging Markets": {"max": 0.15}}
    plan = _plan(cfg)
    assert plan.inert_groups == ("region:emerging markets",)


def test_etf_with_explicit_full_lookthrough_counts_in_emerging_cap(base_cfg):
    overrides = {"EEM": {"region": {"emergents": 1.0}}}
    plan = _plan(base_cfg, overrides=overrides)
    assert coefficient(plan, "region:emergents", "EEM") == 1.0
    assert "EEM" not in plan.unknown_exposures["region"]     # exposition complète : plus inconnue
    constraints.validate_weights(hold(plan, {"EEM": 0.10, "EMA": 0.05}), plan)
    rejected(plan, {"EEM": 0.10, "EMA": 0.06}, "region:emergents")


def test_etf_with_partial_lookthrough_is_counted_pro_rata_and_still_flagged(base_cfg):
    overrides = {"EEM": {"region": {"emergents": 0.6}}}
    plan = _plan(base_cfg, overrides=overrides)
    assert coefficient(plan, "region:emergents", "EEM") == pytest.approx(0.6)
    assert "EEM" in plan.unknown_exposures["region"]         # 40 % restent inconnus
    constraints.validate_weights(hold(plan, {"EEM": 0.10, "EMA": 0.09}), plan)   # 6 % + 9 % = 15 %
    rejected(plan, {"EEM": 0.10, "EMA": 0.10}, "region:emergents")               # 6 % + 10 % = 16 %


# ---------------------------------------------------------------------------
# 7. Classes d'actifs : matières premières, immobilier
# ---------------------------------------------------------------------------
def test_commodities_cap_10_percent(base_cfg):
    plan = _plan(base_cfg)
    constraints.validate_weights(hold(plan, {"GLD": 0.05, "SLV": 0.05}), plan)
    rejected(plan, {"GLD": 0.10, "SLV": 0.05}, "asset_class:commodities")


def test_real_estate_asset_class_cap_15_percent(base_cfg):
    plan = _plan(base_cfg)
    constraints.validate_weights(hold(plan, {"RIT": 0.10, "RIU": 0.05}), plan)
    rejected(plan, {"RIT": 0.10, "RIU": 0.06}, "asset_class:real estate")


# ---------------------------------------------------------------------------
# 8. Optimisation complète sur panel synthétique : plafonds respectés, cash utilisé
# ---------------------------------------------------------------------------
DRIFT = {"crypto": 0.004, "it": 0.0018, "em": 0.0016, "etf": 0.0004, "other": 0.0006}


def _panel(universe, seed=7, n=180):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-02", periods=n)
    rows = []
    for symbol, row in universe.iterrows():
        if row.asset_class == "Alternative":
            drift, vol = DRIFT["crypto"], 0.03
        elif row.sector == "Information Technology":
            drift, vol = DRIFT["it"], 0.014
        elif row.region == "emergents":
            drift, vol = DRIFT["em"], 0.014
        elif row.instrument_type == "ETF":
            drift, vol = DRIFT["etf"], 0.008
        else:
            drift, vol = DRIFT["other"], 0.012
        for date, ret in zip(dates, rng.normal(drift, vol, n)):
            rows.append({"date": date, "symbol": symbol, "total_return_cad": float(ret),
                         "asset_class": row.asset_class, "instrument_type": row.instrument_type,
                         "country": row.country, "sector": row.sector,
                         "is_included_universe": True})
    return pd.DataFrame(rows)


def _hist(cfg):
    cfg["estimation"]["mode"] = "single_method"
    cfg["estimation"]["single_method"] = "historical"
    cfg["data"]["region_overrides"] = {"EMA": "emergents", "EMB": "emergents"}
    cfg["risk_aversion"]["default"] = 2.0
    return cfg


def _by(run, mask_fn):
    w = run.portfolio.weights
    return float(sum(w[s] for s in w.index if s != CASH and mask_fn(s)))


def test_optimizer_respects_every_base_limit_and_agent_does_not():
    universe = _universe()
    panel = _panel(universe)
    base = optimizer.optimize_portfolio(panel, _hist(config.get_base_settings()))
    agent = optimizer.optimize_portfolio(
        panel, _hist(config.get_agent_settings({"risk_aversion_A": 2.0})))

    def sector(name):
        return lambda s: universe.loc[s, "sector"] == name

    crypto_direct = lambda s: universe.loc[s, "instrument_type"] == "Cryptocurrency"   # noqa: E731
    alternative = lambda s: universe.loc[s, "asset_class"] == "Alternative"            # noqa: E731
    emerging = lambda s: s in ("EMA", "EMB")                                           # noqa: E731

    w = base.portfolio.weights
    assert w.drop(CASH).max() <= 0.10 + TOL
    assert _by(base, crypto_direct) <= 0.05 + TOL
    assert _by(base, alternative) <= 0.05 + TOL                  # BTC + ETH + BITW ensemble
    assert _by(base, sector("Information Technology")) <= 0.25 + TOL
    assert _by(base, sector("Financials")) <= 0.30 + TOL
    assert _by(base, sector("Energy")) <= 0.20 + TOL
    assert _by(base, emerging) <= 0.15 + TOL
    assert w.sum() == pytest.approx(1.0)
    constraints.validate_weights(w, base.plan)

    # Non-vacuité : sur les mêmes données, ces limites sont actives en BASE...
    assert _by(base, alternative) > 0.04 and w.drop(CASH).max() > 0.09
    # ... et absentes en AGENT, qui dépasse 10 % par titre et 5 % de crypto.
    assert agent.portfolio.weights.drop(CASH).max() > 0.10 + 1e-3
    assert _by(agent, alternative) > 0.05 + 1e-3
    assert agent.plan.groups == ()
    assert np.allclose(agent.plan.upper_bounds[:len(agent.plan.risky_symbols)], 1.0)


def test_optimizer_base_keeps_etfs_and_crypto_in_the_candidates():
    universe = _universe()
    run = optimizer.optimize_portfolio(_panel(universe), _hist(config.get_base_settings()))
    assert {"XLK", "EEM", "XBB.TO", "BITW", "BTC-CAD", "ETH-CAD"} <= set(run.plan.risky_symbols)
    assert run.plan.unknown_exposures["sector"]
    reported = constraints.unknown_exposure_weights(run.portfolio.weights, run.plan)
    assert set(reported) == {"sector", "region"}
    assert all(0.0 <= v <= 1.0 for v in reported.values())


def _flat(universe, symbols, mu):
    meta = universe.loc[symbols]
    cfg = config.get_base_settings()
    plan = _plan(cfg, meta)
    mu_s = pd.Series(mu, index=symbols, dtype=float)
    cov = pd.DataFrame(np.eye(len(symbols)) * 0.04, index=symbols, columns=symbols)
    return cfg, plan, mu_s, cov


def test_cash_absorbs_the_remainder_when_too_few_assets_for_the_10_percent_cap():
    """5 titres plafonnés à 10 % : au plus 50 % investis, donc au moins 50 % de cash."""
    symbols = ["ITA", "FNA", "ENA", "UTL", "XBB.TO"]
    cfg, plan, mu, cov = _flat(_universe(), symbols, [0.20] * 5)
    result = optimizer.optimize_weights(mu, cov, plan, cfg)
    assert result.weights.drop(CASH).max() <= 0.10 + TOL
    assert result.cash_weight == pytest.approx(0.50, abs=1e-4)
    assert result.weights.sum() == pytest.approx(1.0)


def test_cash_takes_everything_when_all_expected_returns_are_negative():
    symbols = ["ITA", "FNA", "ENA", "UTL", "XBB.TO"]
    cfg, plan, mu, cov = _flat(_universe(), symbols, [-0.05] * 5)
    result = optimizer.optimize_weights(mu, cov, plan, cfg)
    assert result.cash_weight == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 9. Vraies métadonnées du Parquet (échec, jamais skip, si le fichier est absent)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def real_universe():
    source = config.get_parquet_source()
    if not source.startswith("s3://") and not Path(source).is_file():
        pytest.fail(f"Parquet réel introuvable : {source}")
    prepared = data.prepare_optimizer_data(path=source)
    universe = prepared.universe.copy()
    del prepared
    gc.collect()
    return universe


@pytest.fixture(scope="module")
def real_plan(real_universe):
    cfg = config.get_base_settings()
    screened = constraints.filter_eligible_universe(real_universe, cfg)
    return screened, constraints.build_constraint_plan(screened.universe, cfg)


def test_real_nomenclature_matches_every_configured_group(real_universe):
    limits = config.BASE_CONSTRAINTS["group_limits"]
    u = real_universe
    assert set(limits["asset_class"]) <= set(u["asset_class"].dropna().unique())
    assert set(limits["instrument_type"]) <= set(u["instrument_type"].dropna().unique())
    stock_sectors = set(u.loc[u["instrument_type"] == "Stock", "sector"].dropna().unique())
    assert set(limits["sector"]) <= stock_sectors
    # Régions réelles du Parquet : en minuscules, actions seulement. « Emerging Markets » n'existe pas.
    regions = set(u["region"].dropna().unique())
    assert regions == {"usa", "canada", "europe", "asie"}
    assert "Emerging Markets" not in regions and "Emerging Markets" not in limits["region"]
    assert set(limits["region"]) == {"emergents"}  # nom du frontend (catalog.ts) et de monport.py


def test_real_alternative_class_is_exactly_the_crypto_instruments(real_universe):
    u = real_universe
    alt = u[u["asset_class"] == "Alternative"]
    assert set(alt.index) == {"BITW", "BTC-CAD", "ETH-CAD"}
    assert alt.loc["BITW", "instrument_type"] == "ETF"
    assert set(alt.loc[["BTC-CAD", "ETH-CAD"], "instrument_type"]) == {"Cryptocurrency"}


def test_real_estate_asset_class_cap_covers_only_real_estate_etfs_not_reit_stocks(real_universe):
    """Documente une limite connue : les actions du secteur Real Estate sont classées Equity."""
    u = real_universe
    assert set(u.loc[u["asset_class"] == "Real Estate", "instrument_type"]) == {"ETF"}
    reit_stocks = u[(u["instrument_type"] == "Stock") & (u["sector"] == "Real Estate")]
    assert len(reit_stocks) > 0 and set(reit_stocks["asset_class"]) == {"Equity"}
    assert "Real Estate" not in config.BASE_CONSTRAINTS["group_limits"]["sector"]


def test_real_base_does_not_exclude_etfs_or_crypto(real_universe, real_plan):
    screened, _ = real_plan
    u = real_universe
    eligible = u.index[u["is_included_universe"].fillna(False).astype(bool) & (u["observations"] >= 120)]
    assert set(screened.universe.index) == set(eligible)         # BASE ne retire rien d'autre
    kept_types = screened.universe["instrument_type"].value_counts()
    assert kept_types["ETF"] > 50 and kept_types["Cryptocurrency"] == 2
    assert not any(r.startswith("unknown_") for reasons in screened.rejected["reasons"] for r in reasons)


def test_real_agent_with_same_sector_cap_would_reject_every_etf(real_universe):
    cfg = config.get_agent_settings({
        "risk_aversion_A": 5.0, "group_limits": {"sector": {"Information Technology": {"max": 0.25}}}})
    screened = constraints.filter_eligible_universe(real_universe, cfg)
    assert set(screened.universe["instrument_type"]) == {"Stock"}  # comportement strict inchangé en AGENT


def test_real_plan_caps_every_asset_and_counts_known_exposures_only(real_universe, real_plan):
    screened, plan = real_plan
    risky = len(plan.risky_symbols)
    assert np.allclose(plan.upper_bounds[:risky], 0.10) and plan.upper_bounds[-1] == 1.0
    constraints.check_linear_feasibility(plan)
    it_stocks = set(screened.universe.index[(screened.universe["instrument_type"] == "Stock")
                                            & (screened.universe["sector"] == "Information Technology")])
    in_group = {s for s, c in zip(plan.symbols, group(plan, "sector:information technology").coefficients) if c > 0}
    assert in_group == it_stocks and len(it_stocks) > 50
    for etf in ("XLK", "QQQ", "VGT", "SMH"):
        if etf in plan.symbols:
            assert coefficient(plan, "sector:information technology", etf) == 0.0


def test_real_plan_flags_all_unknown_exposures(real_plan):
    screened, plan = real_plan
    u = screened.universe
    non_stock = set(u.index[u["instrument_type"] != "Stock"])
    assert set(plan.unknown_exposures["sector"]) == non_stock
    stocks_without_region = set(u.index[(u["instrument_type"] == "Stock") & u["region"].isna()])
    assert set(plan.unknown_exposures["region"]) == non_stock | stocks_without_region
    assert any("appliqués aux expositions CONNUES" in n for n in plan.notices)


def test_real_emerging_cap_is_inert_today_and_says_so(real_plan):
    _, plan = real_plan
    assert plan.inert_groups == ("region:emergents",)
    assert any("INERTE" in n and "region:emergents" in n for n in plan.notices)


def test_real_crypto_budget_is_shared_between_direct_crypto_and_bitw(real_plan):
    _, plan = real_plan
    assert coefficient(plan, "asset_class:alternative", "BITW") == 1.0
    assert coefficient(plan, "instrument_type:cryptocurrency", "BITW") == 0.0
    rejected(plan, {"BTC-CAD": 0.03, "BITW": 0.03}, "asset_class:alternative")
    constraints.validate_weights(hold(plan, {"BTC-CAD": 0.03, "BITW": 0.02}), plan)
    constraints.validate_weights(hold(plan, {"BITW": 0.05}), plan)


def test_real_summary_is_json_ready(real_plan):
    _, plan = real_plan
    summary = constraints.summarize_plan(plan)
    json.dumps(summary)
    assert summary["inert_groups"] == ["region:emergents"]
