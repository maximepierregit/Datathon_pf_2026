"""Mélanges 80/20: le nombre de positions reste dans la plage de l'optimiseur (25 à 70, ou la demande du client)."""

import pytest

from invest_agents import monport
from invest_agents.config import PORTFOLIO_HOLDINGS
from invest_agents.schemas import Constraint, ConstraintType as T
from test_blend import FakeMarket, portfolio, weights_of


# --------------------------------------------------------------------------- #
# enforce_minimum avec une plage de positions
# --------------------------------------------------------------------------- #
SMALL = {"A": 0.50, "B": 0.30, "C": 0.15, "D": 0.03, "E": 0.008, "F": 0.006, "G": 0.004, "H": 0.002}


def test_too_few_positions_keeps_the_biggest_small_ones_at_exactly_the_minimum():
    out = monport.enforce_minimum(SMALL, {}, min_count=6)
    assert set(out) == {"A", "B", "C", "D", "E", "F"}  # E et F sont les plus grosses des positions sous 1 %
    assert out["E"] == pytest.approx(0.01) and out["F"] == pytest.approx(0.01)
    assert sum(out.values()) == pytest.approx(1.0)
    assert min(out.values()) >= 0.01 - 1e-9
    assert out["A"] / out["B"] == pytest.approx(0.50 / 0.30, rel=1e-3)  # l'emprunt pèse sur les plus grosses, au prorata


def test_without_a_count_range_small_positions_are_just_dropped():
    out = monport.enforce_minimum(SMALL, {})
    assert set(out) == {"A", "B", "C", "D"} and sum(out.values()) == pytest.approx(1.0)


def test_too_many_positions_cuts_the_smallest():
    many = {f"S{i}": w for i, w in enumerate([0.20, 0.15, 0.12, 0.10, 0.09, 0.08, 0.07, 0.06, 0.05, 0.04, 0.03, 0.01])}
    out = monport.enforce_minimum(many, {}, max_count=8)
    assert set(out) == {f"S{i}" for i in range(8)}  # les 8 plus grosses
    assert sum(out.values()) == pytest.approx(1.0) and min(out.values()) >= 0.01


def test_a_range_that_cannot_be_reached_keeps_what_exists():
    out = monport.enforce_minimum({"A": 0.6, "B": 0.4}, {}, min_count=25)
    assert out == pytest.approx({"A": 0.6, "B": 0.4})  # il n'y a que 2 titres: on ne peut pas inventer des positions


def test_raising_to_the_minimum_respects_the_caps_of_the_others():
    out = monport.enforce_minimum({"A": 0.55, "B": 0.40, "C": 0.04, "D": 0.006, "E": 0.004}, {"A": 0.55, "B": 0.5, "C": 1.0},
                                  min_count=4)
    assert out["A"] <= 0.55 + 1e-9  # A est déjà à son plafond: l'emprunt vient de B
    assert set(out) == {"A", "B", "C", "D"} and sum(out.values()) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# La plage elle-même: celle de l'optimiseur, ajustée à la demande du client
# --------------------------------------------------------------------------- #
class Settings:
    settings: dict = {}


def test_range_defaults_to_the_optimizers():
    assert monport.position_range(Settings(), []) == (PORTFOLIO_HOLDINGS["min_count"], PORTFOLIO_HOLDINGS["max_count"]) == (25, 70)


def test_range_follows_the_clients_hard_position_limits():
    hard = lambda t, v: Constraint(type=t, value=v, hard=True)  # noqa: E731
    assert monport.position_range(Settings(), [hard(T.MIN_POSITIONS, 30)]) == (30, 70)
    assert monport.position_range(Settings(), [hard(T.MAX_POSITIONS, 20)]) == (20, 20)  # le minimum suit le maximum du client
    assert monport.position_range(Settings(), [hard(T.MIN_POSITIONS, 80)]) == (80, 80)
    soft = Constraint(type=T.MIN_POSITIONS, value=50, hard=False)
    assert monport.position_range(Settings(), [soft]) == (25, 70)  # une préférence ne change pas la plage


def test_range_does_not_modify_the_shared_default():
    monport.position_range(Settings(), [Constraint(type=T.MIN_POSITIONS, value=40, hard=True)])
    assert PORTFOLIO_HOLDINGS["min_count"] == 25  # la configuration partagée n'est pas touchée


# --------------------------------------------------------------------------- #
# blend
# --------------------------------------------------------------------------- #
def test_blend_keeps_the_position_count_in_range():
    symbols = list("ABCDEFGHIJ")
    core = portfolio("prudent", {s: 0.1 for s in symbols})  # 10 positions
    satellite = portfolio("conviction", {"A": 0.5, "B": 0.5})
    # Sans plage, le mélange garde ses 10 positions. Avec un minimum de 12, il manque 2 positions: impossible (10 titres au total).
    b = monport.blend(FakeMarket(), "prudent", core, satellite, count=(12, 70))
    assert len(b.positions) == 10
    capped = monport.blend(FakeMarket(), "prudent", core, satellite, count=(2, 6))
    assert len(capped.positions) == 6 and sum(weights_of(capped).values()) == pytest.approx(1.0, abs=1e-9)
    assert min(weights_of(capped).values()) >= 0.01
