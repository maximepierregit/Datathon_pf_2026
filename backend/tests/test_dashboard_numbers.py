"""Chiffres du tableau de bord calculés par le backend: VaR/ES et distribution quotidiennes, projection, répartitions,
montants, contributions aux facteurs."""

import numpy as np
import pandas as pd
import pytest

from invest_agents import factors, monport
from invest_agents.backtest import DAILY_LIMIT, DAILY_STEP, daily_distribution, simulate, summarize
from invest_agents.projection import PER_YEAR, clean_contribution, project, projection_view
from invest_agents.schemas import Portfolio, Position


# --------------------------------------------------------------------------- #
# Rendements quotidiens du portefeuille, VaR, ES et distribution
# --------------------------------------------------------------------------- #
def daily_series(values) -> pd.Series:
    return pd.Series(values, index=pd.bdate_range("2021-01-04", periods=len(values)))


def test_daily_portfolio_return_is_sum_of_weight_times_return():
    index = pd.bdate_range("2024-01-01", periods=5)
    r = pd.DataFrame({"A": [0.02, 0.01, -0.01, 0.0, 0.03], "B": [0.0, 0.01, 0.02, -0.02, 0.01], "C": [-0.01, 0.0, 0.0, 0.01, 0.0]}, index=index)
    w = np.array([0.5, 0.3, 0.2])
    out = simulate(r, w, "deux-semaines")  # une seule date de rééquilibrage dans ces 5 jours: le premier jour
    assert out.iloc[0] == pytest.approx(0.5 * 0.02 + 0.3 * 0.0 + 0.2 * -0.01)
    drifted = w * (1 + r.iloc[0].to_numpy())
    drifted /= drifted.sum()  # les poids dérivent avec les rendements du jour 1
    assert out.iloc[1] == pytest.approx(float(drifted @ r.iloc[1].to_numpy()))


def test_var_and_es_come_from_daily_returns():
    rng = np.random.default_rng(3)
    daily = daily_series(rng.normal(0.0004, 0.011, 1500))
    stats = summarize(daily, rf=0.0)["stats"]
    q = float(np.quantile(daily, 0.05))
    assert stats["var95"] == pytest.approx(-q, abs=1e-4)
    assert stats["es95"] == pytest.approx(-float(daily[daily <= q].mean()), abs=1e-4)
    assert stats["es95"] >= stats["var95"] > 0  # l'ES (moyenne de la queue) est au moins aussi grave que la VaR


def test_distribution_buckets_are_half_points_and_sum_to_one():
    rng = np.random.default_rng(4)
    dist = daily_distribution(daily_series(rng.normal(0, 0.01, 2000)), threshold=-0.016)
    buckets = [d["bucket"] for d in dist]
    assert buckets[0] == -DAILY_LIMIT and buckets[-1] == DAILY_LIMIT
    assert all(b - a == pytest.approx(DAILY_STEP) for a, b in zip(buckets, buckets[1:]))
    assert sum(d["share"] for d in dist) == pytest.approx(1.0, abs=2e-3)


def test_distribution_puts_each_day_in_the_nearest_bucket_and_clips_extremes():
    dist = {d["bucket"]: d["share"] for d in daily_distribution(daily_series([0.0, 0.004, 0.0074, -0.02, 0.5, -0.5]), threshold=-0.02)}
    assert dist[0.0] == pytest.approx(1 / 6, abs=1e-3)  # 0 %
    assert dist[0.5] == pytest.approx(2 / 6, abs=1e-3)  # +0,4 % et +0,74 % sont plus près de +0,5 %
    assert dist[-2.0] == pytest.approx(1 / 6, abs=1e-3)
    assert dist[DAILY_LIMIT] == pytest.approx(1 / 6, abs=1e-3)  # +50 % est rangé dans la tranche de l'extrémité
    assert dist[-DAILY_LIMIT] == pytest.approx(1 / 6, abs=1e-3)


def test_tail_starts_at_the_bucket_containing_the_var():
    dist = daily_distribution(daily_series(np.linspace(-0.03, 0.03, 600)), threshold=-0.0109)
    red = [d["bucket"] for d in dist if d["tail"]]
    assert max(red) == -1.0  # la VaR (−1,09 %) tombe dans la tranche autour de −1 %
    assert min(red) == -DAILY_LIMIT


def test_summary_has_cumulative_series_and_drawdown():
    run = summarize(daily_series([0.01] * 300), rf=0.0)
    assert run["stats"]["cumulativeReturn"] == pytest.approx(1.01 ** 300 - 1, abs=1e-3)
    assert run["series"][-1]["cumulative"] == pytest.approx(run["stats"]["cumulativeReturn"], abs=1e-3)
    assert all(row["drawdown"] == 0.0 for row in run["series"])  # un portefeuille qui ne fait que monter n'a aucun recul


# --------------------------------------------------------------------------- #
# Projection sur 10 ans
# --------------------------------------------------------------------------- #
def test_projection_compounds_the_annual_return_divided_by_periods():
    rows = project(1000.0, {"frequency": "deux-semaines", "amount": 100}, mu=0.0, sigma=0.0)
    assert rows[1]["expected"] == pytest.approx(1000 + 26 * 100)  # sans rendement: capital + versements
    rows = project(1000.0, {"frequency": "deux-semaines", "amount": 100}, mu=0.26, sigma=0.0, years=1)
    value = 1000.0
    for _ in range(26):
        value = value * (1 + 0.26 / 26) + 100
    assert rows[1]["expected"] == pytest.approx(value, abs=0.01)


def test_projection_invested_amount_and_frequencies():
    for frequency, per_year in (("deux-semaines", 26), ("mensuelle", 12), ("annuelle", 1)):
        rows = project(500.0, {"frequency": frequency, "amount": 50}, mu=0.05, sigma=0.1)
        assert PER_YEAR[frequency] == per_year
        assert rows[10]["invested"] == pytest.approx(500 + 50 * per_year * 10)
    rows = project(500.0, {"frequency": "aucune", "amount": 50}, mu=0.05, sigma=0.1)
    assert rows[10]["invested"] == 500.0  # « aucune »: pas d'ajouts, même si un montant est fourni
    assert rows[10]["expected"] == pytest.approx(500 * (1 + 0.05 / 12) ** 120, abs=0.01)


def test_projection_cones_are_ordered_centered_and_reproducible():
    a = project(10_000.0, {"frequency": "mensuelle", "amount": 200}, mu=0.07, sigma=0.12)
    assert a == project(10_000.0, {"frequency": "mensuelle", "amount": 200}, mu=0.07, sigma=0.12)  # graine fixe
    for row in a[1:]:
        assert row["p05"] <= row["p25"] <= row["p75"] <= row["p95"]
    last = a[-1]
    assert last["p25"] < last["expected"] < last["p75"]  # le rendement moyen est au milieu du cône probable
    calm = project(10_000.0, {"frequency": "mensuelle", "amount": 200}, mu=0.07, sigma=0.02)[-1]
    assert (calm["p95"] - calm["p05"]) < (last["p95"] - last["p05"])  # plus de volatilité, cône plus large


def test_projection_without_volatility_has_no_cone():
    last = project(1000.0, {"frequency": "annuelle", "amount": 100}, mu=0.05, sigma=0.0)[-1]
    assert last["p05"] == pytest.approx(last["expected"], abs=0.01) == pytest.approx(last["p95"], abs=0.01)


def test_projection_view_describes_itself():
    view = projection_view(1000.0, {"frequency": "deux-semaines", "amount": 100}, mu=0.05, sigma=0.1)
    assert view["periodsPerYear"] == 26 and view["contribution"] == {"frequency": "deux-semaines", "amount": 100.0}
    assert len(view["rows"]) == 11 and view["rows"][0]["year"] == 0 and view["rows"][-1]["year"] == 10
    assert projection_view(1000.0, "n'importe quoi", 0.05, 0.1)["contribution"]["frequency"] == "aucune"


@pytest.mark.parametrize("raw", [None, {}, {"frequency": "hebdo", "amount": 5}, {"frequency": "mensuelle", "amount": -5},
                                 {"frequency": "mensuelle", "amount": "abc"}, {"frequency": "mensuelle", "amount": 1e12}, "x"])
def test_invalid_contribution_means_no_contribution(raw):
    assert clean_contribution(raw) == {"frequency": "aucune", "amount": 0.0}


# --------------------------------------------------------------------------- #
# Répartitions, montants, contributions aux facteurs
# --------------------------------------------------------------------------- #
HOLDINGS = [
    {"ticker": "A", "assetClass": "actions", "weight": 0.40, "region": "canada", "sector": "Technologie"},
    {"ticker": "B", "assetClass": "actions", "weight": 0.20, "region": "usa", "sector": "Santé"},
    {"ticker": "C", "assetClass": "actions", "weight": 0.10, "region": "usa", "sector": None},
    {"ticker": "D", "assetClass": "obligations", "weight": 0.30, "region": "canada", "sector": None},
]


def test_breakdowns_sum_to_one_and_are_sorted():
    b = monport.breakdowns(HOLDINGS)
    for rows in b.values():
        assert sum(r["weight"] for r in rows) == pytest.approx(1.0)
        assert [r["weight"] for r in rows] == sorted((r["weight"] for r in rows), reverse=True)
    assert {r["key"]: r["weight"] for r in b["classe"]} == {"actions": 0.7, "obligations": 0.3}
    assert {r["key"]: r["weight"] for r in b["region"]} == {"canada": 0.7, "usa": 0.3}
    sectors = {r["key"]: r["weight"] for r in b["secteur"]}
    assert sectors["Actions diversifiées (FNB)"] == 0.1  # un FNB d'actions sans secteur
    assert sectors["Obligations"] == 0.3


def test_amounts_are_computed_on_the_starting_amount():
    a = monport.amounts_view(25_000.0, expected_return=0.06, worst_year=-0.2)
    assert a == {"start": 25_000.0, "expectedGain": 1500.0, "worstYearLoss": -5000.0, "worstYearValue": 20_000.0}


@pytest.fixture
def scored(monkeypatch):
    table = pd.DataFrame(
        {"momentum": [0.5, -0.2, 1.0, 0.0], "quality": [1.0, 0.4, -0.6, 0.2], "value": [-0.5, 0.3, 0.1, 0.0],
         "growth": [0.8, 0.0, 0.2, -0.4], "small_cap": [0.1, -0.3, 0.0, 0.6]},
        index=["S1", "S2", "S3", "S4"])
    monkeypatch.setattr(factors, "_cache", table)
    return table


def portfolio(weights: dict[str, float]) -> Portfolio:
    positions = [Position(symbol=s, name=s, weight=w, sector="", country="", asset_class="") for s, w in weights.items()]
    return Portfolio(id="equilibre", mandate="m", mandate_description="", positions=positions)


def test_factor_contributions_add_up_to_the_exposure(scored):
    weights = {"S1": 0.30, "S2": 0.20, "S3": 0.10, "S4": 0.10, "ETF1": 0.30}  # un FNB, sans score
    view = monport.factor_view(portfolio(weights))
    assert view["coverage"] == pytest.approx(0.7)
    for factor, exposure in view["exposure"].items():
        total = sum(s["contributions"][factor] for s in view["stocks"]) + (view["others"]["contributions"][factor] if view["others"] else 0)
        assert total == pytest.approx(exposure, abs=2e-3)
    s1 = view["stocks"][0]
    assert s1["ticker"] == "S1" and s1["contributions"]["qualite"] == pytest.approx(0.30 * 1.0 / 0.7, abs=1e-3)  # w × z ÷ part notée


def test_factor_view_groups_the_stocks_beyond_the_top(scored, monkeypatch):
    monkeypatch.setattr(monport, "FACTOR_TOP", 2)
    view = monport.factor_view(portfolio({"S1": 0.4, "S2": 0.3, "S3": 0.2, "S4": 0.1}))
    assert [s["ticker"] for s in view["stocks"]] == ["S1", "S2"] and view["stockCount"] == 4
    assert view["others"]["count"] == 2 and view["others"]["weight"] == pytest.approx(0.3)


def test_factor_requests_say_whether_the_target_is_met(scored):
    view = monport.factor_view(portfolio({"S1": 0.5, "S2": 0.5}), {"factors": {"qualite": 2, "value": -1, "croissance": 1, "momentum": 0}})
    assert view["exposure"]["qualite"] == pytest.approx(0.7)  # (1,0 + 0,4) / 2
    assert view["requests"]["qualite"] == {"level": 2, "threshold": 0.5, "met": True}  # Imposer: au moins +0,5
    assert view["exposure"]["value"] == pytest.approx(-0.1)  # (−0,5 + 0,3) / 2
    assert view["requests"]["value"] == {"level": -1, "threshold": -0.2, "met": False}  # Moins: au plus −0,2
    assert view["requests"]["croissance"]["met"] is True  # (0,8 + 0,0) / 2 = +0,4, au-dessus de +0,2
    assert "momentum" not in view["requests"]  # niveau 0: rien demandé
    only_s1 = monport.factor_view(portfolio({"S1": 1.0}), {"factors": {"value": -1}})
    assert only_s1["requests"]["value"]["met"] is True  # −0,5 ≤ −0,2


def test_factor_view_without_scored_stocks_is_empty(scored):
    view = monport.factor_view(portfolio({"ETF1": 1.0}))
    assert view["coverage"] == 0 and view["stocks"] == [] and view["others"] is None and view["requests"] == {}
