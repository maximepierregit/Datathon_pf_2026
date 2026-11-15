"""Profil de risque V2: capacité C, tolérance T, position S et aversion A (monport.py)."""

import pytest

from invest_agents import monport

# L'exemple de référence du scoring V2.
EXAMPLE = {"age": 35, "horizon": 15, "amount": 10000, "lossReaction": 2, "objective": "fructifier", "comfort": 3,
           "contribution": {"frequency": "mensuelle", "amount": 100}}


def test_example_matches_v2_reference():
    # a = 0,8; h = 14/19; ajouts = 0,6 × 0,2 + 0,4 × 0,48 = 0,312
    assert monport.contribution_score(EXAMPLE) == pytest.approx(0.312)
    assert monport.capacity(EXAMPLE) == pytest.approx(0.45 * 0.8 + 0.30 * 14 / 19 + 0.25 * 0.312)
    assert monport.tolerance(EXAMPLE) == pytest.approx(0.5 * 2 / 3 + 0.3 * 0.5 + 0.2 * 0.5)
    s = monport.risk_position(EXAMPLE)
    assert s == pytest.approx(0.6591 / 2 + 0.5833 / 2, abs=1e-3)
    assert monport.risk_aversion(s) == pytest.approx(3.2, abs=0.01)


def test_no_contribution_scores_zero():
    profile = {**EXAMPLE, "contribution": {"frequency": "aucune", "amount": 100}}
    assert monport.contribution_score(profile) == 0
    assert monport.contribution_score({k: v for k, v in EXAMPLE.items() if k != "contribution"}) == 0


@pytest.mark.parametrize("frequency, per_year", [("deux-semaines", 26), ("mensuelle", 12), ("annuelle", 1),
                                                 ("biweekly", 26), ("monthly", 12), ("yearly", 1)])
def test_frequencies(frequency, per_year):
    profile = {"amount": 1_000_000, "contribution": {"frequency": frequency, "amount": 60}}
    annual = 60 * per_year
    expected = 0.6 * annual / 12 / 500 + 0.4 * annual / 1_000_000 / 0.25
    assert monport.contribution_score(profile) == pytest.approx(expected)


def test_contribution_scores_are_capped():
    profile = {"amount": 1000, "contribution": {"frequency": "mensuelle", "amount": 5000}}
    assert monport.contribution_score(profile) == pytest.approx(1.0)


def test_tolerance_caps_capacity_too():
    # Capacité maximale, tolérance nulle: S ne dépasse pas T + 0,125.
    profile = {"age": 18, "horizon": 30, "amount": 1000, "lossReaction": 0, "objective": "securiser", "comfort": 1,
               "contribution": {"frequency": "mensuelle", "amount": 1000}}
    assert monport.tolerance(profile) == 0
    assert monport.risk_position(profile) == pytest.approx(monport.CAPACITY_MARGIN)


def test_aversion_anchors():
    for s, a in monport.AVERSION_ANCHORS:
        assert monport.risk_aversion(s) == pytest.approx(a)


def test_questionnaire_merges_contribution():
    profile, prefs = monport._questionnaire({"profile": {"age": 40}, "contribution": {"frequency": "annuelle", "amount": 5},
                                             "constraints": {"classes": {}}})
    assert profile == {"age": 40, "contribution": {"frequency": "annuelle", "amount": 5}}
    assert prefs == {"classes": {}}
