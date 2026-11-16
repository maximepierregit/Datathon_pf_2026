"""Questionnaire Exclure / Neutre / Pourcentage exact, du frontend jusqu'aux poids optimisés.

Règles vérifiées: trois modes d'instruments; classes d'actifs sur tous les instruments admissibles (FNB compris);
régions, secteurs et thématiques sur les actions détenues en direct SEULEMENT; pourcentages en part du portefeuille
total; contradictions détectées avant l'optimisation; aucune contamination entre les modes BASE et AGENT.
"""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from invest_agents import config, constraints, monport, optimizer
from invest_agents.catalog import agent_request, detect_conflicts, evaluate
from invest_agents.schemas import Constraint, ConstraintType as T


# --------------------------------------------------------------------------- #
# Univers de démonstration (même forme que data.build_universe)
# --------------------------------------------------------------------------- #
ROWS = [
    # symbol, class, instrument, sector, country, theme
    ("AAPL", "Equity", "Stock", "Information Technology", "United States", "tech"),
    ("NVDA", "Equity", "Stock", "Information Technology", "United States", "ia;tech"),
    ("JPM", "Equity", "Stock", "Financials", "United States", None),
    ("RY.TO", "Equity", "Stock", "Financials", "Canada", None),
    ("SHOP.TO", "Equity", "Stock", "Information Technology", "Canada", "tech"),
    ("SAP.DE", "Equity", "Stock", "Information Technology", "Germany", "tech"),
    ("LMT", "Equity", "Stock", "Industrials", "United States", "armement"),
    ("SPY", "Equity", "ETF", "Non classé", "Non classé", "tech"),  # FNB tagué tech: ne compte jamais
    ("XIU.TO", "Equity", "ETF", "Non classé", "Non classé", None),
    ("XBB.TO", "Fixed Income", "ETF", "Non classé", "Non classé", None),
    ("AGG", "Fixed Income", "ETF", "Non classé", "Non classé", None),
    ("GLD", "Commodities", "ETF", "Non classé", "Non classé", None),
    ("BITW", "Alternative", "ETF", "Non classé", "Non classé", None),
    ("BTC-CAD", "Alternative", "Cryptocurrency", "Non classé", "Non classé", None),
]
STOCKS = [r[0] for r in ROWS if r[2] == "Stock"]
ETFS = [r[0] for r in ROWS if r[2] == "ETF"]


def universe() -> pd.DataFrame:
    u = pd.DataFrame(ROWS, columns=["symbol", "asset_class", "instrument_type", "sector", "country", "theme"])
    u["observations"], u["is_included_universe"] = 1000, True
    return u.set_index("symbol")


def agent(**request):
    return config.get_agent_settings({"risk_aversion_A": 5.0, **request})


def exact(weight):
    return {"mode": "exact", "weight": weight}


EXCLUDE = {"mode": "exclude", "weight": None}


def plan(cfg):
    screened = constraints.filter_eligible_universe(universe(), cfg)
    return constraints.build_constraint_plan(screened.universe, cfg)


def solve(cfg):
    """Optimisation réelle (SLSQP + règle 0 ou >= 1 %), rendements et risques simples et distincts."""
    p = plan(cfg)
    risky = list(p.risky_symbols)
    rng = np.random.default_rng(7)
    mu = pd.Series(np.linspace(0.03, 0.12, len(risky)), index=risky)
    root = rng.normal(0, 0.05, (len(risky), len(risky)))
    cov = pd.DataFrame(root @ root.T + np.eye(len(risky)) * 0.02, index=risky, columns=risky)
    result = optimizer.optimize_weights(mu, cov, p, cfg)
    return p, result.weights


def group(p, name):
    return next(g for g in p.groups if g.name == name)


def exposure(weights, symbols):
    return float(sum(weights.get(s, 0.0) for s in symbols))


EQUITY = [r[0] for r in ROWS if r[1] == "Equity"]  # la poche actions: actions en direct ET FNB d'actions


def sleeve(weights, symbols):
    """Part de la poche actions tenue par ces titres."""
    return exposure(weights, symbols) / exposure(weights, EQUITY)


def members(p, name):
    g = group(p, name)
    return {s for s in p.symbols if g.coefficients[p.index_of(s)] > 0}


# --------------------------------------------------------------------------- #
# Contrat de config.py
# --------------------------------------------------------------------------- #
def test_preference_normalization_and_validation():
    cfg = agent(preferences={"theme": {"tech": exact(0.45), "ia": "neutral", "armement": "exclude"}})
    assert cfg["agent_preferences"] == {"theme": {"tech": exact(0.45), "armement": EXCLUDE}}  # neutre retiré


@pytest.mark.parametrize("bad, message", [
    (exact(45), "fraction"),                       # 45 n'est pas 45 fois le capital
    (exact(-0.1), "fraction"),
    (exact(float("nan")), "fini"),
    ({"mode": "exact"}, "exige un poids"),
    ({"mode": "exclude", "weight": 0.2}, "n'accepte pas de poids"),
    ({"mode": "neutral", "weight": 0.2}, "n'accepte pas de poids"),
    ("more", "inconnu"),
])
def test_invalid_preferences_are_refused(bad, message):
    with pytest.raises((ValueError, TypeError), match=message):
        agent(preferences={"theme": {"tech": bad}})


def test_instrument_selection_modes_and_alias():
    assert config.get_base_settings()["constraints"]["instrument_selection"] == "mixed"
    for mode in config.INSTRUMENT_SELECTION:
        assert agent(instrument_selection=mode)["constraints"]["instrument_selection"] == mode
    assert agent(etf_only=True)["constraints"]["instrument_selection"] == "etf_only"
    with pytest.raises(ValueError, match="contredit"):
        agent(etf_only=True, instrument_selection="stocks_only")
    with pytest.raises(ValueError, match="instrument_selection"):
        agent(instrument_selection="bonds_only")


# --------------------------------------------------------------------------- #
# Question 1: instruments admissibles
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mode, kept", [
    ("etf_only", set(ETFS)),
    ("mixed", set(STOCKS) | set(ETFS) | {"BTC-CAD"}),
    ("stocks_only", set(STOCKS) | {"BTC-CAD"}),
])
def test_three_instrument_modes(mode, kept):
    cfg = agent(instrument_selection=mode)
    p = plan(cfg)
    assert set(p.risky_symbols) == kept
    assert p.cash_symbol == "CASH-CAD"  # le cash synthétique reste permis


def test_etf_only_keeps_equity_etfs_and_not_bitw_as_crypto():
    p = plan(agent(instrument_selection="etf_only"))
    assert {"SPY", "XIU.TO", "BITW"} <= set(p.risky_symbols)  # exposition Equity via FNB != action en direct
    assert "BTC-CAD" not in p.risky_symbols


# --------------------------------------------------------------------------- #
# Question 2: classes d'actifs (tous les instruments admissibles)
# --------------------------------------------------------------------------- #
def test_exact_asset_class_counts_etfs_and_is_respected():
    cfg = agent(preferences={"asset_class": {"Fixed Income": exact(0.30)}})
    p, w = solve(cfg)
    g = group(p, "pref_exact:asset_class:fixed income")
    assert g.minimum == g.maximum == pytest.approx(0.30)
    assert exposure(w, ["XBB.TO", "AGG"]) == pytest.approx(0.30, abs=1e-6)


def test_excluded_asset_class_is_zero():
    p, w = solve(agent(preferences={"asset_class": {"Equity": EXCLUDE}}))
    assert not set(p.risky_symbols) & (set(STOCKS) | {"SPY", "XIU.TO"})
    assert exposure(w, STOCKS + ["SPY", "XIU.TO"]) == 0.0


def test_crypto_is_direct_crypto_not_the_whole_alternative_class():
    p, w = solve(agent(preferences={"instrument_type": {"Cryptocurrency": exact(0.05)}}))
    g = group(p, "pref_exact:instrument_type:cryptocurrency")
    assert g.coefficients[p.index_of("BTC-CAD")] == 1.0 and g.coefficients[p.index_of("BITW")] == 0.0
    assert w["BTC-CAD"] == pytest.approx(0.05, abs=1e-6)


# --------------------------------------------------------------------------- #
# Questions 3 et 4: actions détenues en direct seulement
# --------------------------------------------------------------------------- #
def test_region_coefficients_ignore_etfs():
    cfg = agent(preferences={"country": {"Canada": exact(0.30), "United States": exact(0.20),
                                         "France|Germany": EXCLUDE}})
    p = plan(cfg)
    share = group(p, "pref_exact:country:canada")
    # (e_g − 0,30 × equity) @ w = 0: une action canadienne vaut 0,70, un FNB d'actions −0,30 (poche seulement)
    assert share.coefficients[p.index_of("RY.TO")] == pytest.approx(0.70)
    assert share.coefficients[p.index_of("XIU.TO")] == pytest.approx(-0.30)  # FNB canadien: jamais dans le groupe
    assert share.coefficients[p.index_of("XBB.TO")] == 0.0  # hors poche actions
    assert share.minimum == share.maximum == 0.0
    assert members(p, "pref_presence:country:canada") == {"RY.TO", "SHOP.TO"}
    assert "SAP.DE" not in p.risky_symbols  # Europe exclue: l'action allemande disparaît...
    assert {"SPY", "XIU.TO"} <= set(p.risky_symbols)  # ...mais aucun FNB n'est retiré


def test_region_percent_is_a_share_of_the_equity_sleeve():
    cfg = agent(preferences={"country": {"Canada": exact(0.30), "United States": exact(0.20)}})
    _, w = solve(cfg)
    assert sleeve(w, ["RY.TO", "SHOP.TO"]) == pytest.approx(0.30, abs=1e-5)
    assert sleeve(w, ["AAPL", "NVDA", "JPM", "LMT"]) == pytest.approx(0.20, abs=1e-5)
    assert exposure(w, ["RY.TO", "SHOP.TO"]) >= 0.01  # au moins une action canadienne détenue
    assert float(w.sum()) == pytest.approx(1.0)


def test_theme_exact_counts_only_tagged_stocks():
    cfg = agent(preferences={"theme": {"tech": exact(0.45)}})
    p, w = solve(cfg)
    tagged = {"AAPL", "NVDA", "SHOP.TO", "SAP.DE"}
    assert members(p, "pref_presence:theme:tech") == tagged
    assert group(p, "pref_exact:theme:tech").coefficients[p.index_of("SPY")] == pytest.approx(-0.45)  # FNB tagué
    assert sleeve(w, sorted(tagged)) == pytest.approx(0.45, abs=1e-5)


def test_equity_etfs_dilute_the_share_but_never_fill_it():
    """30 % de la poche en actions canadiennes: XIU.TO grossit la poche, il ne remplit pas la part."""
    p = plan(agent(preferences={"country": {"Canada": exact(0.30)}}))
    w = pd.Series(0.0, index=p.symbols)
    w["RY.TO"], w["XIU.TO"], w["XBB.TO"] = 0.15, 0.35, 0.50  # poche = 50 %, Canada en direct = 15 %
    constraints.validate_weights(w.to_numpy(), p)
    w["RY.TO"], w["XIU.TO"], w["SPY"] = 0.10, 0.20, 0.20  # le FNB canadien ne compte pas: 20 % de la poche
    with pytest.raises(constraints.ConstraintInfeasibleError, match="canada"):
        constraints.validate_weights(w.to_numpy(), p)


def test_empty_equity_sleeve_cannot_satisfy_a_share():
    """Sans action détenue, 0 = 0,45 × 0 serait respecté à vide: la présence d'une action du groupe est exigée."""
    p = plan(agent(preferences={"theme": {"tech": exact(0.45)}}))
    w = pd.Series(0.0, index=p.symbols)
    w["XBB.TO"], w["CASH-CAD"] = 0.60, 0.40
    with pytest.raises(constraints.ConstraintInfeasibleError, match="presence"):
        constraints.validate_weights(w.to_numpy(), p)


def test_overlapping_themes_are_each_respected():
    """NVDA est ia ET tech: chaque groupe le compte, les pourcentages ne s'additionnent pas."""
    cfg = agent(preferences={"theme": {"tech": exact(0.45), "ia": exact(0.20)}})
    _, w = solve(cfg)
    assert sleeve(w, ["AAPL", "NVDA", "SHOP.TO", "SAP.DE"]) == pytest.approx(0.45, abs=1e-5)
    assert sleeve(w, ["NVDA"]) == pytest.approx(0.20, abs=1e-5)


def test_theme_exclusion_removes_stocks_not_etfs():
    p = plan(agent(preferences={"theme": {"tech": EXCLUDE}}))
    assert not {"AAPL", "NVDA", "SHOP.TO", "SAP.DE"} & set(p.risky_symbols)
    assert "SPY" in p.risky_symbols


def test_sector_union_group():
    cfg = agent(preferences={"sector": {"Financials|Industrials": exact(0.25)}})
    _, w = solve(cfg)
    assert sleeve(w, ["JPM", "RY.TO", "LMT"]) == pytest.approx(0.25, abs=1e-5)


def test_class_and_share_combine():
    """Actions 40 % du portefeuille et Technologie 45 % de la poche: 18 % du portefeuille en actions tech."""
    cfg = agent(preferences={"asset_class": {"Equity": exact(0.40)}, "theme": {"tech": exact(0.45)}})
    _, w = solve(cfg)
    assert exposure(w, EQUITY) == pytest.approx(0.40, abs=1e-6)
    assert exposure(w, ["AAPL", "NVDA", "SHOP.TO", "SAP.DE"]) == pytest.approx(0.18, abs=1e-5)


# --------------------------------------------------------------------------- #
# Neutre, 0 %, 45 %, 100 %
# --------------------------------------------------------------------------- #
def test_neutral_adds_no_constraint():
    assert plan(agent(preferences={"theme": {"tech": "neutral"}})).groups == plan(agent()).groups
    assert not [g for g in plan(agent()).groups if g.name.startswith("pref_")]


def test_zero_percent_is_an_exclusion():
    p, w = solve(agent(preferences={"theme": {"tech": exact(0.0)}}))
    assert not {"AAPL", "NVDA", "SHOP.TO", "SAP.DE"} & set(p.risky_symbols)
    assert exposure(w, ["AAPL", "NVDA", "SHOP.TO", "SAP.DE"]) == 0.0


def test_hundred_percent():
    _, w = solve(agent(preferences={"asset_class": {"Fixed Income": exact(1.0)}}))
    assert exposure(w, ["XBB.TO", "AGG"]) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize("raw, fraction", [(0, 0.0), (45, 0.45), (100, 1.0), (12.5, 0.125),
                                           (145, None), (-5, None), (float("inf"), None), (True, None)])
def test_frontend_percent_is_converted_once(raw, fraction):
    assert monport.share_of(raw) == fraction


# --------------------------------------------------------------------------- #
# Contradictions détectées avant l'optimisation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("request_, message", [
    ({"instrument_selection": "etf_only", "preferences": {"theme": {"tech": exact(0.45)}}}, "FNB seulement"),
    ({"instrument_selection": "stocks_only", "preferences": {"asset_class": {"Fixed Income": exact(0.30)}}},
     "aucun instrument admissible"),
    ({"preferences": {"asset_class": {"Equity": EXCLUDE}, "country": {"Canada": exact(0.30)}}},
     "actions détenues en direct"),
    ({"preferences": {"asset_class": {"Fixed Income": exact(0.60), "Equity": exact(0.50)}}}, "totalisent 110"),
])
def test_contradictions_raise_before_optimization(request_, message):
    with pytest.raises(constraints.ConstraintInfeasibleError, match=message):
        constraints.filter_eligible_universe(universe(), agent(**request_))


def test_required_symbol_in_excluded_theme_is_refused():
    cfg = agent(required_symbols=["NVDA"], preferences={"theme": {"tech": EXCLUDE}})
    with pytest.raises(constraints.ConstraintInfeasibleError, match="requis"):
        constraints.filter_eligible_universe(universe(), cfg)


def test_overlapping_themes_are_not_summed():
    plan(agent(preferences={"theme": {"tech": exact(0.70), "ia": exact(0.60)}}))  # NVDA porte les deux


def test_exactness_vs_concentration_cap_is_infeasible():
    """Actions 90 % et Canada 50 % de la poche = 45 % du portefeuille, mais 2 actions canadiennes à 10 % max: 20 %."""
    cfg = agent(max_weight_per_asset=0.10, preferences={"asset_class": {"Equity": exact(0.90)},
                                                        "country": {"Canada": exact(0.50)}})
    with pytest.raises(constraints.ConstraintInfeasibleError):
        constraints.check_linear_feasibility(plan(cfg))


def test_feasible_linear_system_passes():
    cfg = agent(max_weight_per_asset=0.10, preferences={"country": {"Canada": exact(0.30)}})
    constraints.check_linear_feasibility(plan(cfg))  # la poche actions s'ajuste à 20 % / 30 %


def test_final_validation_rejects_weights_off_target():
    p = plan(agent(preferences={"asset_class": {"Fixed Income": exact(0.30)}}))
    w = pd.Series(0.0, index=p.symbols)
    w["XBB.TO"], w["CASH-CAD"] = 0.25, 0.75
    with pytest.raises(constraints.ConstraintInfeasibleError, match="fixed income"):
        constraints.validate_weights(w.to_numpy(), p)


# --------------------------------------------------------------------------- #
# Séparation BASE / AGENT
# --------------------------------------------------------------------------- #
def test_agent_does_not_inherit_base_constraints():
    cfg = agent(preferences={"theme": {"tech": exact(0.45)}})
    assert cfg["constraints"]["max_weight_per_asset"] is None  # BASE: 10 %
    assert cfg["constraints"]["group_limits"]["asset_class"] == {}  # BASE: Alternative 5 %, ...
    assert "unknown_exposure_policy" not in cfg["constraints"]


def test_agent_run_does_not_leak_into_base():
    before = config.get_base_settings()
    solve(agent(instrument_selection="stocks_only", preferences={"theme": {"tech": exact(0.45)}}))
    after = config.get_base_settings()
    assert after == before and after["agent_preferences"] == {}
    assert after["constraints"]["instrument_selection"] == "mixed"


# --------------------------------------------------------------------------- #
# Du questionnaire du frontend au moteur (monport -> catalog -> config)
# --------------------------------------------------------------------------- #
def market():
    u = universe()
    allowed = {
        "sector": sorted(set(u["sector"]) - {"Non classé"}), "country": sorted(set(u["country"]) - {"Non classé"}),
        "asset_class": sorted(set(u["asset_class"])), "instrument_type": sorted(set(u["instrument_type"])),
        "theme": ["armement", "ia", "tech"], "symbol": sorted(u.index),
    }
    return SimpleNamespace(assets=u, portfolio_metrics=lambda _w: (_ for _ in ()).throw(ValueError())), allowed


FRONT = {
    "vehicles": "tous",
    "classes": {"obligations": 30, "crypto": "exclure"},
    "regions": {"canada": 30, "europe": "exclure"},
    "themes": {"tech": 35, "ia": 20, "finance": 10},
}


def test_frontend_answers_become_engine_preferences():
    mk, allowed = market()
    out, skipped = monport.preference_constraints(FRONT, allowed)
    request = agent_request(mk, out)
    assert request["instrument_selection"] == "mixed"
    assert request["excluded_instrument_types"] == ["Cryptocurrency"]
    prefs = request["preferences"]
    assert prefs["asset_class"] == {"Fixed Income": exact(0.30)}
    assert prefs["country"]["Canada"] == exact(0.30)
    assert prefs["country"]["Germany"] == EXCLUDE  # l'Europe, pays par pays
    assert prefs["theme"] == {"ia": exact(0.20)}  # étiquette vérifiée du Parquet
    # Technologie = secteur GICS « Information Technology » (choix de main), comme les autres thématiques sectorielles.
    assert prefs["sector"] == {"Information Technology": exact(0.35), "Financials": exact(0.10)}
    assert not detect_conflicts(out)
    # Et le moteur l'accepte tel quel.
    config.get_agent_settings(request)


@pytest.mark.parametrize("vehicles, mode", [("fnb", "etf_only"), ("titres", "stocks_only"), ("tous", "mixed")])
def test_frontend_vehicles_become_instrument_selection(vehicles, mode):
    mk, allowed = market()
    out, _ = monport.preference_constraints({"vehicles": vehicles}, allowed)
    assert agent_request(mk, out)["instrument_selection"] == mode


def test_evaluate_measures_the_share_of_the_equity_sleeve():
    mk, allowed = market()
    out, _ = monport.preference_constraints({"vehicles": "tous", "regions": {"canada": 30}}, allowed)
    ok = evaluate(mk, {"RY.TO": 0.15, "SPY": 0.35, "XBB.TO": 0.50}, out)  # 15 % / 50 % de poche = 30 %
    padded = evaluate(mk, {"RY.TO": 0.10, "XIU.TO": 0.20, "SPY": 0.20, "XBB.TO": 0.50}, out)  # XIU.TO ne compte pas
    no_stocks = evaluate(mk, {"XBB.TO": 1.0}, out)
    assert [c.passed for c in ok] == [True] and ok[0].actual == pytest.approx(0.30)
    assert [c.passed for c in padded] == [False] and padded[0].actual == pytest.approx(0.20)
    assert [c.passed for c in no_stocks] == [False]


@pytest.mark.parametrize("front, message", [
    ({"vehicles": "fnb", "classes": {"crypto": 5}}, "crypto"),
    ({"vehicles": "fnb", "themes": {"tech": 45}}, "FNB seulement"),
    ({"vehicles": "titres", "classes": {"obligations": 30}}, "Titres individuels"),
    ({"classes": {"actions": "exclure"}, "regions": {"canada": 30}}, "actions sont exclues"),
    ({"regions": {"canada": 70, "usa": 40}}, "110"),
])
def test_questionnaire_contradictions_are_reported(front, message):
    assert any(message in m for m in monport.preference_contradictions(front))


def test_shares_are_not_compared_to_the_equity_percent():
    """Actions 40 %, Canada 30 % + États-Unis 20 % de la poche, Technologie 45 % de la poche: tout se tient."""
    assert monport.preference_contradictions({"classes": {"actions": 40}, "regions": {"canada": 30, "usa": 20},
                                              "themes": {"tech": 45}}) == []


def test_exact_and_exclusion_on_same_target_conflict():
    exclude = Constraint(type=T.EXCLUDE_INSTRUMENT_TYPE, target="Cryptocurrency", hard=True)
    crypto = Constraint(type=T.EXACT_INSTRUMENT_TYPE_WEIGHT, target="Cryptocurrency", value=0.05, hard=True)
    assert detect_conflicts([exclude, crypto])
