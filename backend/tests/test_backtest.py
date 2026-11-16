"""Backtest: dates de rééquilibrage, dérive des poids entre deux dates, titres cotés en cours de route."""

import numpy as np
import pandas as pd
import pytest

from invest_agents.backtest import backtest, rebalance_mask, simulate


def frame(days: int, columns: dict[str, float], start: str = "2024-01-01") -> pd.DataFrame:
    """Rendements quotidiens constants par titre, sur des jours ouvrables."""
    index = pd.bdate_range(start, periods=days)
    return pd.DataFrame({k: np.full(days, v) for k, v in columns.items()}, index=index)


def test_rebalance_dates():
    index = pd.bdate_range("2024-01-01", periods=70)
    biweekly = rebalance_mask(index, "deux-semaines")
    assert list(np.flatnonzero(biweekly)) == list(range(0, 70, 10))
    monthly = rebalance_mask(index, "mensuelle")
    assert all(index[i].day <= 3 for i in np.flatnonzero(monthly)[1:])  # premier jour ouvrable du mois
    assert monthly.sum() == 4  # janvier (départ), février, mars, avril
    assert rebalance_mask(index, "aucune").sum() == 1
    with pytest.raises(ValueError):
        rebalance_mask(index, "hebdo")


def test_never_rebalancing_is_buy_and_hold():
    rng = np.random.default_rng(0)
    r = pd.DataFrame(rng.normal(0.0005, 0.01, (300, 3)), index=pd.bdate_range("2024-01-01", periods=300))
    w = np.array([0.5, 0.3, 0.2])
    value = (1 + simulate(r, w, "aucune")).prod()
    held = float(w @ (1 + r).prod().to_numpy())  # chaque titre composé seul, sans jamais toucher aux poids
    assert value == pytest.approx(held, rel=1e-10)


def test_weights_drift_then_reset():
    # A monte de 1 %/jour, B ne bouge pas: sans rééquilibrage, A pèse de plus en plus.
    r = frame(40, {"A": 0.01, "B": 0.0})
    w = np.array([0.5, 0.5])
    never = simulate(r, w, "aucune")
    biweekly = simulate(r, w, "deux-semaines")
    assert never.iloc[0] == pytest.approx(0.005)  # 50 % × 1 %
    assert never.iloc[-1] > biweekly.iloc[-1]  # la part de A a dérivé à la hausse
    assert biweekly.iloc[10] == pytest.approx(0.005)  # jour 10: retour à 50/50
    assert biweekly.iloc[9] > 0.005  # la veille, A pesait plus de 50 %


def test_frequencies_give_different_paths():
    # Deux titres opposés: plus on rééquilibre rarement, plus le résultat s'écarte.
    rng = np.random.default_rng(1)
    common = rng.normal(0, 0.01, 600)
    r = pd.DataFrame({"A": common + 0.001, "B": -common}, index=pd.bdate_range("2021-01-01", periods=600))
    w = np.array([0.5, 0.5])
    finals = {f: float((1 + simulate(r, w, f)).prod()) for f in ("deux-semaines", "mensuelle", "annuelle", "aucune")}
    assert len({round(v, 6) for v in finals.values()}) == 4


def test_late_listing_spreads_its_weight_then_joins():
    r = frame(400, {"A": 0.001, "B": 0.002})
    r.iloc[:100, 1] = np.nan  # B est coté à partir du jour 100
    out = backtest(r, {"A": 0.5, "B": 0.5}, rf=0.0)
    assert out is not None and out["start"] == r.index[0].strftime("%Y-%m-%d")
    # Avant B: 100 % A (0,1 %/jour). Après: rééquilibrage immédiat à 50/50.
    daily = simulate(r.fillna(0.0), np.array([0.5, 0.5]), "aucune", np.column_stack([np.ones(400, bool), np.arange(400) >= 100]))
    assert daily.iloc[50] == pytest.approx(0.001)
    assert daily.iloc[100] == pytest.approx(0.0015)


def test_short_history_gives_none():
    assert backtest(frame(100, {"A": 0.001}), {"A": 1.0}, rf=0.0) is None
