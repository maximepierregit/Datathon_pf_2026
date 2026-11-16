"""Pipeline MonPort: filtre d'historique 2021, mu individuel, Sigma Ledoit-Wolf commune, Markowitz global sur tout
l'univers, 25 à 60 positions détenues (cible 50), trois variantes qui ne diffèrent que par A.

Marché synthétique réaliste: jours fériés différents par place (New York, Toronto, Paris), crypto cotée tous les
jours ouvrables dès le 1er janvier 2021, titres listés en 2022 et en 2025.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from invest_agents import allocator, config, monport
from invest_agents.agents.portfolio_manager import make_pm_worker
from invest_agents.market import (Market, estimate_expected_returns, history_filter, ledoit_wolf_universe,
                                  synchronized_returns)
from invest_agents.schemas import Constraint, ConstraintType as T, InvestorForm, PepiteReview

DATES = pd.bdate_range("2021-01-01", "2026-11-09")  # le 1er janvier 2021 est un vendredi: seule la crypto y cote
SECTORS = ["Information Technology", "Financials", "Health Care", "Energy", "Industrials", "Consumer Staples"]


def make_market(n_us=40, n_ca=25, n_eu=10, n_etf_eq=10, n_bond=12, seed=0, late=True) -> Market:
    rng = np.random.default_rng(seed)
    rows, series = [], {}
    market_factor = rng.normal(0.0004, 0.009, len(DATES))
    sector_factor = {s: rng.normal(0, 0.006, len(DATES)) for s in SECTORS}
    holidays = {place: set(rng.choice(np.arange(1, len(DATES)), 9 * 6, replace=False)) for place in ("us", "ca", "eu")}
    holidays["us"].add(0); holidays["ca"].add(0); holidays["eu"].add(0)  # 1er janvier: aucune bourse ouverte
    rate = rng.normal(0.0001, 0.002, len(DATES))

    def add(symbol, cls, kind, sector, country, place, beta, noise, drift, theme=None, start=0):
        r = drift + beta * market_factor + (sector_factor[sector] if sector in sector_factor else 0) \
            + rng.normal(0, noise, len(DATES))
        if cls == "Fixed Income":
            r = 0.00012 + rate + 0.05 * market_factor + rng.normal(0, noise, len(DATES))
        s = pd.Series(r, index=DATES)
        closed = [DATES[i] for i in holidays.get(place, ())]
        s.loc[closed] = np.nan
        s.iloc[:start] = np.nan
        series[symbol] = s
        rows.append(dict(symbol=symbol, name=symbol, sector=sector, industry="Non classé", country=country,
                         currency="CAD", asset_class=cls, instrument_type=kind, market=place, theme=theme))

    for i in range(n_us):
        add(f"US{i}", "Equity", "Stock", SECTORS[i % 6], "United States", "us", rng.uniform(0.6, 1.4), 0.012,
            rng.normal(0.0002, 0.0002), theme="tech" if i % 6 == 0 else None)
    for i in range(n_ca):
        add(f"CA{i}.TO", "Equity", "Stock", SECTORS[i % 6], "Canada", "ca", rng.uniform(0.6, 1.2), 0.011,
            rng.normal(0.0002, 0.0002), theme="tech" if i % 6 == 0 else None)
    for i in range(n_eu):
        add(f"EU{i}.PA", "Equity", "Stock", SECTORS[i % 6], "France", "eu", rng.uniform(0.6, 1.2), 0.012,
            rng.normal(0.00015, 0.0002))
    add("SPY", "Equity", "ETF", "Non classé", "Non classé", "us", 1.0, 0.002, 0.0003)
    for i in range(n_etf_eq - 1):
        add(f"EQ{i}", "Equity", "ETF", "Non classé", "Non classé", "us" if i % 2 else "ca", rng.uniform(0.8, 1.1),
            0.004, 0.00025)
    for i in range(n_bond):
        add(f"BND{i}", "Fixed Income", "ETF", "Non classé", "Non classé", "us" if i % 2 else "ca", 0, 0.002, 0)
    add("GLD", "Commodities", "ETF", "Non classé", "Non classé", "us", 0.1, 0.009, 0.0003)
    add("BTC-CAD", "Alternative", "Cryptocurrency", "Non classé", "Non classé", "crypto", 1.5, 0.03, 0.001)
    if late:  # titres listés après le début de l'horizon
        add("NEW22", "Equity", "Stock", "Energy", "United States", "us", 1.0, 0.012, 0.0004, start=260)
        add("NEW25", "Equity", "Stock", "Health Care", "Canada", "ca", 1.0, 0.012, 0.0008, start=1100)
        add("JAN18", "Equity", "Stock", "Industrials", "France", "eu", 1.0, 0.012, 0.0003, start=12)
    returns = pd.DataFrame(series)
    assets = pd.DataFrame(rows).set_index("symbol")
    assets["ann_return"] = returns.mean() * 252  # historique individuel complet
    assets["ann_vol"] = returns.std() * np.sqrt(252)
    assets["sharpe"] = (assets["ann_return"] - 0.035) / assets["ann_vol"]
    assets["n_obs"] = returns.count()
    return Market(assets=assets, returns=returns, settings=config.get_settings())


@pytest.fixture(scope="module")
def mk():
    return make_market()


def hard(*cs):
    return [Constraint(type=t, target=target, value=value, hard=True) for t, target, value in cs]


LIMITS = hard((T.MAX_POSITION_WEIGHT, None, 0.40), (T.MAX_STOCK_WEIGHT, None, 0.08))


# --------------------------------------------------------------------------- #
# Filtre d'historique
# --------------------------------------------------------------------------- #
def test_history_filter_keeps_jan_2021_and_excludes_late_listings(mk):
    h = mk.history()
    assert h.horizon_start == pd.Timestamp("2021-01-01")  # première date du panel (crypto)
    assert {"US0", "CA0.TO", "EU0.PA", "BTC-CAD", "BND0"} <= set(h.eligible)  # 4 janvier pour les bourses
    assert set(h.excluded.index) == {"NEW22", "NEW25", "JAN18"}
    assert h.excluded.loc["NEW25", "first_date"] == DATES[1100].date()
    assert h.excluded.loc["JAN18", "instrument_type"] == "Stock"


def test_different_holidays_do_not_cause_false_exclusions(mk):
    """Chaque place a des jours fériés différents: aucun titre coté dès la première semaine n'est exclu."""
    h = mk.history()
    assert len(h.eligible) == mk.returns.shape[1] - 3


def test_original_data_is_not_modified(mk):
    before = mk.returns.copy()
    mk.history()
    mk.universe_covariance()
    pd.testing.assert_frame_equal(mk.returns, before)
    assert {"NEW22", "NEW25", "JAN18"} <= set(mk.assets.index)  # toujours dans le marché, hors optimisation


# --------------------------------------------------------------------------- #
# mu: historique individuel maximal
# --------------------------------------------------------------------------- #
def test_return_windows_use_full_individual_history():
    est = config.ESTIMATION
    assert est["historical"]["lookback_observations"] is None
    assert est["capm_shrinkage"]["lookback_observations"] is None
    assert est["capm_shrinkage"]["historical_lookback_observations"] is None
    assert est["ewma"]["lookback_observations"] is None


def test_mu_is_not_limited_to_common_dates(mk):
    """La crypto cote les jours fériés des bourses: son mu utilise tous ses jours, pas les dates communes."""
    meta = mk.assets
    settings = config.get_settings()
    settings["estimation"]["mode"] = "single_method"
    mu = estimate_expected_returns(mk.returns[["BTC-CAD", "US0"]], meta, settings)
    assert mu.loc["BTC-CAD", "mu"] == pytest.approx(mk.returns["BTC-CAD"].mean() * 252)
    common = mk.returns[["BTC-CAD", "US0"]].dropna()
    assert len(common) < mk.returns["BTC-CAD"].count()


@pytest.mark.parametrize("method", ["historical", "ewma", "capm_shrinkage", "capm_benchmark_shrinkage"])
def test_four_return_methods_still_work(mk, method):
    settings = config.get_settings()
    settings["estimation"]["mode"] = "single_method"
    settings["estimation"]["single_method"] = method
    settings["benchmarks"]["stock_country_sector"] = {}
    settings["benchmarks"]["stock_country"] = {"United States": "SPY"}
    settings["benchmarks"]["etf_overrides"] = {"SPY": "US1"}  # IYY n'existe pas dans ce marché synthétique
    settings["estimation"]["capm_benchmark_shrinkage"]["erp_annual_by_benchmark"] = {"SPY": 0.05, "US1": 0.05}
    mu = estimate_expected_returns(mk.returns[["US0", "US1", "SPY"]], mk.assets, settings)
    assert np.isfinite(mu.loc["US0", "mu"])


def test_no_look_ahead_column_in_estimation():
    assert config.DATA["return_column"] != config.DATA["forward_return_column"]


# --------------------------------------------------------------------------- #
# Sigma: Ledoit-Wolf sur les rendements synchronisés depuis 2021
# --------------------------------------------------------------------------- #
def test_synchronized_returns_have_no_gaps_and_keep_cumulative_returns(mk):
    h = mk.history()
    window = mk.returns.loc[mk.returns.index >= h.horizon_start, list(h.eligible)]
    synced, info = synchronized_returns(window, h.horizon_start)
    assert not synced.isna().any().any()
    assert synced.shape == (info["common_observations"], len(h.eligible))
    # Le rendement cumulé de chaque titre est exactement conservé (les jours fériés sont recomposés, pas perdus).
    for s in ("US0", "CA0.TO", "EU0.PA", "BTC-CAD"):
        last = synced.index[-1]
        assert np.prod(1 + synced[s]) == pytest.approx(np.prod(1 + window.loc[:last, s].dropna()), rel=1e-9)
    assert info["calendar_dates_removed"] == int(window.isna().any(axis=1).sum())


def test_universe_covariance_is_one_ledoit_wolf_matrix(mk):
    from sklearn.covariance import LedoitWolf

    sigma, d = mk.universe_covariance()
    h = mk.history()
    assert list(sigma.index) == list(h.eligible) and sigma.shape == (len(h.eligible),) * 2
    assert np.allclose(sigma.to_numpy(), sigma.to_numpy().T)
    assert d["minimum_eigenvalue"] > -1e-10
    assert 0 < d["shrinkage_coefficient"] < 1
    synced, info = synchronized_returns(mk.returns[list(h.eligible)], h.horizon_start)
    expected = LedoitWolf().fit(synced.to_numpy()).covariance_ * info["periods_per_year_effective"]
    assert np.allclose(sigma.to_numpy(), expected)
    assert d["assets_excluded_for_short_history"] == 3 and d["calendar_dates_removed"] > 0
    assert d["common_observations"] > 1000  # le filtre garde ~5,8 ans de dates communes


def test_late_listing_would_have_shrunk_the_common_sample():
    """Sans le filtre, NEW25 réduirait l'échantillon commun à moins de 2 ans."""
    m = make_market()
    h = m.history()
    with_late = synchronized_returns(m.returns, h.horizon_start)[1]["common_observations"]
    without = synchronized_returns(m.returns[list(h.eligible)], h.horizon_start)[1]["common_observations"]
    assert with_late < 500 < without


# --------------------------------------------------------------------------- #
# Markowitz global et nombre de positions
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def runs(mk):
    out = {}
    for name, a in (("prudent", 14.0), ("equilibre", 7.0), ("conviction", 3.5)):
        out[name] = allocator.optimize_universe(mk, "mean_variance", LIMITS, risk_aversion=a)
    return out


def test_all_eligible_assets_enter_markowitz(mk, runs):
    d = runs["equilibre"].diagnostics
    assert d["initial_universe"] == len(mk.assets)
    assert d["eligible_after_history_filter"] == len(mk.history().eligible)
    assert d["assets_sent_to_markowitz"] == len(mk.history().eligible)
    assert sorted(d["excluded_for_short_history"]) == ["JAN18", "NEW22", "NEW25"]


def test_holdings_range_and_minimum_weight(runs):
    for r in runs.values():
        assert r.ok, r.message
        w = r.weights
        assert 25 <= len(w) <= 70
        assert r.diagnostics["holdings_range"] == [25, 70]
        assert min(w.values()) >= 0.01 - 1e-4
        assert sum(w.values()) == pytest.approx(1.0, abs=1e-6)
        assert r.diagnostics["constraints_satisfied"]


def test_markowitz_alone_concentrates_and_selection_documents_it(runs):
    d = runs["equilibre"].diagnostics
    assert d["positive_weights_initial"] < 25  # l'optimum continu est concentré
    assert len(d["added_for_count"]) > 0  # titres ajoutés par utilité marginale (covariance comprise)
    assert d["utility_final"] <= d["utility_initial_optimum"] + 1e-9


def realistic_market():
    """Rendements espérés ramenés entre 2 % et 14 %: la diversification ajoutée coûte alors peu d'utilité."""
    m = make_market(n_us=120, n_ca=60, n_eu=20, n_etf_eq=20, n_bond=12, seed=5)
    a = m.assets
    a["ann_return"] = 0.02 + 0.12 * (a["ann_return"] - a["ann_return"].min()) / (
        a["ann_return"].max() - a["ann_return"].min())
    return m


def test_holdings_count_is_not_fixed_and_follows_the_cost_rule():
    """Pas de cible fixe: au-delà de 25, un titre n'est ajouté que s'il coûte au plus 1 point de base d'utilité."""
    m = realistic_market()
    r = allocator.optimize_universe(m, "mean_variance", LIMITS, risk_aversion=7.0)
    assert r.ok, r.message
    d = r.diagnostics
    assert 25 < len(r.weights) < 70  # ni le minimum, ni le maximum: le nombre vient du coût
    assert d["added_for_diversification"] > 0
    stricter = allocator.optimize_universe(m, "mean_variance", LIMITS, risk_aversion=7.0,
                                           holdings={**config.PORTFOLIO_HOLDINGS, "max_marginal_utility_cost": 0.0})
    assert len(stricter.weights) < len(r.weights)  # sans tolérance de coût, on s'arrête plus tôt


def test_client_asking_for_two_holdings_overrides_the_range(mk):
    # Deux lignes plafonnées à 40 % ne font pas 100 %: le client qui veut 2 titres a aussi un plafond adapté.
    cs = hard((T.MAX_POSITION_WEIGHT, None, 0.60), (T.MAX_POSITIONS, None, 2))
    r = allocator.optimize_universe(mk, "mean_variance", cs, risk_aversion=7.0)
    assert r.ok, r.message
    assert len(r.weights) == 2 and r.diagnostics["holdings_range"] == [2, 2]


def test_tiny_universe_goes_below_minimum_with_a_note(mk):
    """Tout exclu sauf la crypto: un seul titre admissible, détenu à 100 %, et le diagnostic l'explique."""
    cs = hard((T.EXCLUDE_ASSET_CLASS, "Equity", None), (T.EXCLUDE_ASSET_CLASS, "Fixed Income", None),
              (T.EXCLUDE_ASSET_CLASS, "Commodities", None))
    r = allocator.optimize_universe(mk, "mean_variance", cs, risk_aversion=7.0)
    assert r.ok, r.message
    assert r.weights == {"BTC-CAD": 1.0}
    assert any("sous le minimum" in n for n in r.diagnostics["count_notes"])


def test_concentration_and_risk_contributions_are_reported(runs):
    d = runs["equilibre"].diagnostics
    assert d["effective_holdings_count"] > 10
    assert 0 < d["top_5_weight"] < 1
    assert len(d["risk_contributions_top"]) == 5


def test_exact_preferences_are_respected_globally(mk):
    cs = LIMITS + hard((T.EXACT_ASSET_CLASS_WEIGHT, "Fixed Income", 0.30), (T.EXACT_THEME_WEIGHT, "tech", 0.25),
                       (T.EXCLUDE_COUNTRY, "France", None))
    r = allocator.optimize_universe(mk, "mean_variance", cs, risk_aversion=7.0)
    assert r.ok, r.message
    w = r.weights
    a = mk.assets
    assert sum(v for s, v in w.items() if a.at[s, "asset_class"] == "Fixed Income") == pytest.approx(0.30, abs=2e-3)
    equity = sum(v for s, v in w.items() if a.at[s, "asset_class"] == "Equity")
    tech = sum(v for s, v in w.items() if a.at[s, "instrument_type"] == "Stock" and a.at[s, "theme"] == "tech")
    assert tech / equity == pytest.approx(0.25, abs=5e-3)  # part de la poche actions
    assert not any(a.at[s, "country"] == "France" for s in w)


def test_small_universe_holds_everything_it_can(mk):
    """Avec seulement les obligations admissibles (12 FNB), le portefeuille en détient au plus 12, et le dit."""
    cs = LIMITS + hard(*[(T.EXCLUDE_ASSET_CLASS, c, None) for c in ("Equity", "Commodities", "Alternative")])
    r = allocator.optimize_universe(mk, "mean_variance", cs, risk_aversion=7.0)
    assert r.ok, r.message
    assert len(r.weights) <= 12 and r.diagnostics["count_notes"]


def test_judge_and_risk_prompts_no_longer_ask_for_rebuilds():
    from invest_agents.workflow import workers

    judge = " ".join(workers.JUDGE_SYSTEM.split())
    risk = " ".join(workers.RISK_SYSTEM.split())
    assert "Demande une réoptimisation" not in judge and "reconstruit d'office" not in judge
    assert "corriger sans enfreindre" not in risk and "demander une réoptimisation" not in risk
    # Le choix du gagnant, lui, ne change pas: conformité, puis note du juge, puis Sharpe.
    assert "PROFIL COHÉRENT" in judge and "diversification" in judge


def test_history_filter_contradiction_is_reported():
    """Le seul titre Health Care canadien coté au début est absent: une préférence qui l'exige devient infaisable."""
    m = make_market(n_ca=0)  # plus d'actions canadiennes, sauf NEW25 (exclue par l'historique)
    cs = LIMITS + hard((T.EXACT_COUNTRY_WEIGHT, "Canada", 0.20))
    r = allocator.optimize_universe(m, "mean_variance", cs, risk_aversion=7.0)
    assert not r.ok and "NEW25" in r.message


# --------------------------------------------------------------------------- #
# Trois variantes: seul A change
# --------------------------------------------------------------------------- #
def check(position=0.45, coherent=True):
    return monport.assess({"age": 40, "horizon": 12, "lossReaction": 2, "objective": "fructifier", "comfort": 3},
                          PepiteReview(summary="", coherent=coherent)).model_copy(update={"risk_position": position})


def test_variants_use_s_minus_s_plus_and_log_interpolation():
    c = check(0.45)
    a = {s: monport.objective_for(s, c)[1] for s in monport.SLOTS}
    assert a == {"prudent": monport.risk_aversion(0.35), "equilibre": monport.risk_aversion(0.45),
                 "conviction": monport.risk_aversion(0.55)}
    edge = check(0.05)
    assert monport.objective_for("prudent", edge)[1] == monport.risk_aversion(0.0)  # max(0, S − 0,10)


def test_variants_share_every_constraint():
    c = check(0.45)
    allowed = {"asset_class": ["Equity", "Fixed Income"], "instrument_type": ["ETF", "Stock"], "sector": [],
               "country": [], "symbol": [], "theme": []}
    profiles, _ = monport.build_profiles(None, c, [], allowed)
    described = {s: sorted(f"{x.type.value}:{x.target}:{x.value}" for x in cs) for s, (_, cs) in profiles.items()}
    assert described["prudent"] == described["equilibre"] == described["conviction"]


def test_variants_share_mu_sigma_and_universe(mk, runs):
    d = {s: r.diagnostics for s, r in runs.items()}
    assert len({x["assets_sent_to_markowitz"] for x in d.values()}) == 1
    assert len({str(x["covariance"]) for x in d.values()}) == 1  # même Sigma (calculée une fois par marché)
    assert mk.universe_covariance() is mk.universe_covariance()


def test_variants_differ_only_through_a(runs):
    vols = {s: r.metrics.volatility for s, r in runs.items()}
    assert vols["prudent"] <= vols["equilibre"] + 1e-4 <= vols["conviction"] + 2e-4
    assert {s: r.diagnostics["A_effective"] for s, r in runs.items()} == {"prudent": 14.0, "equilibre": 7.0,
                                                                          "conviction": 3.5}


# --------------------------------------------------------------------------- #
# Le gestionnaire LLM ne sélectionne plus de titres
# --------------------------------------------------------------------------- #
def test_portfolio_manager_has_no_selection_tool(mk):
    from invest_agents.mandates import Mandate
    from invest_agents.schemas import InvestorProfile

    mandate = Mandate(id="equilibre", name="Variante fidèle", objective="mean_variance", description="",
                      guidance="", vol_cap_factor=None, risk_aversion=7.0)
    form = InvestorForm(age=40, investment_amount_cad=10000, horizon_years=10, risk_tolerance=3,
                        max_acceptable_loss_pct=25, objective="balanced", experience="intermediate",
                        liquidity_needs="low", constraints=[])
    worker = make_pm_worker(mk, mandate, InvestorProfile(form=form, assessment=check(), constraints=[]), [])
    names = set(worker.handle.agent.tool_names)
    assert "get_portfolio" in names
    assert not names & {"optimize_portfolio", "screen_assets", "describe_universe", "screen_factor"}
    prompt = " ".join(worker.handle.agent.system_prompt.split()).lower()
    assert "choisis entre" not in prompt and "tu ne choisis aucun titre" in prompt


# --------------------------------------------------------------------------- #
# Performance (taille réelle) et vrai Parquet
# --------------------------------------------------------------------------- #
def test_performance_at_real_universe_size():
    """~780 titres sur 5,8 ans: Ledoit-Wolf et Markowitz global doivent rester dans un temps raisonnable."""
    m = make_market(n_us=470, n_ca=180, n_eu=60, n_etf_eq=45, n_bond=12, seed=3)
    t = time.perf_counter()
    _, d = m.universe_covariance()
    lw_seconds = time.perf_counter() - t
    r = allocator.optimize_universe(m, "mean_variance", LIMITS, risk_aversion=7.0)
    print(f"\n[performance] titres={d['assets_after_history_filter']} dates_communes={d['common_observations']} "
          f"Ledoit-Wolf={lw_seconds:.1f}s optimisation={r.diagnostics.get('seconds_initial_optimization')}s "
          f"sélection+réoptimisation={r.diagnostics.get('seconds_selection_and_reoptimization')}s "
          f"total={r.diagnostics.get('seconds_total')}s positions={len(r.weights)}")
    assert r.ok, r.message
    assert r.diagnostics["assets_sent_to_markowitz"] == len(m.history().eligible) > 750
    assert 25 <= len(r.weights) <= 60


REAL = Path(os.getenv(config.PARQUET_ENV_VAR, config.DEFAULT_PARQUET_PATH))


@pytest.mark.skipif(not REAL.exists(), reason=f"Parquet réel introuvable: {REAL}")
def test_real_parquet_pipeline():
    from invest_agents.market import get_market

    m = get_market()
    h = m.history()
    print("\n[réel] exclus pour historique court:\n", h.excluded.to_string())
    _, d = m.universe_covariance()
    print("[réel] Sigma:", d)
    for slot, a in (("prudente", 14.0), ("fidèle", 7.0), ("audacieuse", 3.5)):
        r = allocator.optimize_universe(m, "mean_variance", LIMITS, risk_aversion=a)
        print(f"[réel] {slot}: {r.status} A={r.diagnostics.get('A_effective')} positions={len(r.weights)} "
              f"vol={r.metrics.volatility if r.metrics else None} rendement={r.metrics.expected_return if r.metrics else None}")
        assert r.ok, r.message
