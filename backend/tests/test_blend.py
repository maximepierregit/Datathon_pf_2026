"""Mélanges 80/20: « 0 ou au moins 1 % » par position, plafonds par titre, somme égale à 1."""

import pandas as pd
import pytest

from invest_agents import monport
from invest_agents.schemas import Constraint, ConstraintType as T, Portfolio, Position


class FakeMarket:
    """Le strict nécessaire à `blend`: les métadonnées des titres (`assets`) et des indicateurs de portefeuille."""

    def __init__(self, funds: set[str] = frozenset()):
        symbols = list("ABCDEFGHIJ") + ["ETF1", "ETF2"]
        self.assets = pd.DataFrame(
            {"name": symbols, "sector": "Technologie", "country": "Canada", "asset_class": "Equity",
             "instrument_type": ["ETF" if s in funds or s.startswith("ETF") else "Stock" for s in symbols]}, index=symbols)

    def portfolio_metrics(self, weights):
        self.last_weights = dict(weights)
        return None


def portfolio(slot: str, weights: dict[str, float]) -> Portfolio:
    positions = [Position(symbol=s, name=s, weight=w, sector="", country="", asset_class="") for s, w in weights.items()]
    return Portfolio(id=slot, mandate=slot, mandate_description="", positions=positions)


def weights_of(p: Portfolio) -> dict[str, float]:
    return {pos.symbol: pos.weight for pos in p.positions}


# --------------------------------------------------------------------------- #
# enforce_minimum
# --------------------------------------------------------------------------- #
def test_enforce_minimum_drops_small_positions_and_spreads_their_weight():
    out = monport.enforce_minimum({"A": 0.60, "B": 0.30, "C": 0.088, "D": 0.008, "E": 0.004}, {})
    assert set(out) == {"A", "B", "C"}
    assert sum(out.values()) == pytest.approx(1.0)
    assert min(out.values()) >= 0.01
    assert out["A"] / out["B"] == pytest.approx(2.0)  # redistribué au prorata des poids


def test_enforce_minimum_leaves_a_valid_portfolio_unchanged():
    w = {"A": 0.5, "B": 0.3, "C": 0.2}
    assert monport.enforce_minimum(w, {}) == pytest.approx(w)


def test_enforce_minimum_respects_the_caps():
    out = monport.enforce_minimum({"A": 0.38, "B": 0.30, "C": 0.30, "D": 0.02, "E": 0.005, "F": 0.005}, {"A": 0.40, "B": 0.40, "C": 0.40})
    assert out["A"] <= 0.40 + 1e-9 and sum(out.values()) == pytest.approx(1.0)
    assert set(out) == {"A", "B", "C", "D"}  # D (2 %) reste: il est au-dessus du minimum


def test_enforce_minimum_never_loses_capital_when_every_cap_is_reached():
    out = monport.enforce_minimum({"A": 0.5, "B": 0.495, "C": 0.005}, {"A": 0.5, "B": 0.5})
    assert sum(out.values()) == pytest.approx(1.0)  # plus de marge: remise à l'échelle


# --------------------------------------------------------------------------- #
# blend
# --------------------------------------------------------------------------- #
def test_blend_has_no_position_under_one_percent():
    core = portfolio("prudent", {"A": 0.40, "B": 0.30, "C": 0.20, "D": 0.09, "E": 0.01})
    satellite = portfolio("conviction", {"A": 0.30, "F": 0.50, "G": 0.15, "H": 0.04, "I": 0.01})
    market = FakeMarket()
    raw_small = [s for s, w in {"E": 0.8 * 0.01, "I": 0.2 * 0.01, "H": 0.2 * 0.04}.items()]  # ce que donnait l'ancien mélange
    assert len(raw_small) == 3
    b = monport.blend(market, "prudent", core, satellite)
    w = weights_of(b)
    assert min(w.values()) >= 0.01
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-9)  # le résidu d'arrondi est placé sur la plus grosse position
    assert not {"E", "I", "H"} & set(w)  # E à 0,8 %, I à 0,2 %, H à 0,8 % ne passent pas le minimum
    assert market.last_weights == pytest.approx(w, abs=1e-3)  # les indicateurs sont calculés sur les poids finaux


def test_blend_keeps_the_80_20_split_for_the_big_positions():
    core = portfolio("prudent", {"A": 0.5, "B": 0.5})
    satellite = portfolio("conviction", {"A": 0.5, "C": 0.5})
    w = weights_of(monport.blend(FakeMarket(), "prudent", core, satellite))
    assert w == pytest.approx({"A": 0.5, "B": 0.4, "C": 0.1})


def test_blend_caps_a_stock_between_the_two_profiles_caps():
    core = portfolio("prudent", {"A": 0.10, "B": 0.10, "C": 0.10, "D": 0.10, "E": 0.10, "F": 0.10, "G": 0.10, "H": 0.10, "I": 0.10, "J": 0.095, "ETF1": 0.005})
    satellite = portfolio("conviction", {"A": 0.10, "B": 0.10, "C": 0.10, "D": 0.10, "E": 0.10, "F": 0.10, "G": 0.10, "H": 0.10, "I": 0.10, "J": 0.10})
    b = monport.blend(FakeMarket(), "prudent", core, satellite, core_cap=0.10, satellite_cap=0.10)
    stocks = {s: w for s, w in weights_of(b).items() if not s.startswith("ETF")}
    assert max(stocks.values()) <= 0.10 + 1e-3  # un titre ne dépasse pas 80 % × 10 % + 20 % × 10 %
    assert sum(weights_of(b).values()) == pytest.approx(1.0, abs=1e-3)


def test_blend_with_a_missing_parent_returns_the_other_one_renamed():
    only = portfolio("conviction", {"A": 0.6, "B": 0.4})
    b = monport.blend(FakeMarket(), "prudent", None, only)
    assert b.id == "prudent" and weights_of(b) == {"A": 0.6, "B": 0.4}


def test_stock_cap_reads_the_hard_stock_limit_of_a_profile():
    limits = [Constraint(type=T.MAX_STOCK_WEIGHT, value=0.12, hard=True), Constraint(type=T.MAX_STOCK_WEIGHT, value=0.08, hard=False)]
    assert monport.stock_cap(limits) == 0.12  # seule la limite dure compte
    assert monport.stock_cap([]) == monport.LINE_CAP
