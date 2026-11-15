"""« FNB seulement » écarte les titres détenus en direct, pas les FNB de la même classe d'actifs."""

from types import SimpleNamespace

import pandas as pd

from invest_agents import monport
from invest_agents.catalog import agent_request, evaluate
from invest_agents.config import INSTRUMENT_SELECTION
from invest_agents.monport import drop_unreachable_floors, preference_constraints
from invest_agents.schemas import Constraint, ConstraintType as T


def market():
    """Comme l'univers réel: un FNB d'actions a la classe « Equity », comme une action."""
    rows = [  # un FNB n'a ni secteur ni pays connu
        ("AAPL", "Equity", "Stock", "Information Technology"),
        ("RY.TO", "Equity", "Stock", "Financials"),
        ("SPY", "Equity", "ETF", "Non classé"),
        ("XBB.TO", "Fixed Income", "ETF", "Non classé"),
        ("GLD", "Alternative", "ETF", "Non classé"),
        ("BTC-CAD", "Alternative", "Cryptocurrency", "Non classé"),
    ]
    assets = pd.DataFrame(rows, columns=["symbol", "asset_class", "instrument_type", "sector"]).set_index("symbol")

    def no_metrics(_weights):
        raise ValueError("pas d'historique dans ce test")

    allowed = {
        "sector": [], "country": [], "symbol": sorted(assets.index),
        "asset_class": sorted(assets["asset_class"].unique()),
        "instrument_type": sorted(assets["instrument_type"].unique()),
    }
    return SimpleNamespace(assets=assets, portfolio_metrics=no_metrics), allowed


def fnb_only(allowed):
    out, _ = preference_constraints({"vehicles": "fnb"}, allowed)
    return out


def test_fnb_only_excludes_instrument_types_not_classes():
    _, allowed = market()
    out = fnb_only(allowed)
    assert {(c.type, c.target) for c in out} == {
        (T.EXCLUDE_INSTRUMENT_TYPE, "Stock"),
        (T.EXCLUDE_INSTRUMENT_TYPE, "Cryptocurrency"),
    }
    assert all(c.hard for c in out)


def test_fnb_only_keeps_equity_etfs():
    """Le moteur reçoit le mode d'instruments, pas une liste de symboles: les FNB d'actions restent admissibles."""
    mk, allowed = market()
    request = agent_request(mk, fnb_only(allowed))
    assert request["instrument_selection"] == "etf_only"
    assert request["excluded_symbols"] == [] and request["excluded_asset_classes"] == []
    assert set(mk.assets.index[agent_mask(mk, fnb_only(allowed))]) == {"AAPL", "RY.TO", "BTC-CAD"}


def test_fnb_only_flags_a_direct_stock():
    mk, allowed = market()
    checks = evaluate(mk, {"SPY": 0.6, "AAPL": 0.4}, fnb_only(allowed))
    assert [c.constraint.target for c in checks if not c.passed] == ["Stock"]


def test_all_vehicles_excludes_nothing():
    _, allowed = market()
    out, _ = preference_constraints({"vehicles": "tous"}, allowed)
    assert out == []


def test_unreachable_floor_is_dropped_with_a_note(monkeypatch):
    """FNB seulement et plus de techno: aucun FNB n'a de secteur, le plancher techno ferait échouer les gestionnaires."""
    mk, allowed = market()
    monkeypatch.setattr(monport, "excluded_mask", lambda m, cs: agent_mask(m, cs))
    tech = Constraint(type=T.MIN_SECTOR_WEIGHT, target="Information Technology", value=0.10, hard=True)
    bonds = Constraint(type=T.MIN_ASSET_CLASS_WEIGHT, target="Fixed Income", value=0.20, hard=True)
    kept, note = drop_unreachable_floors(mk, fnb_only(allowed) + [tech, bonds])
    assert tech not in kept and bonds in kept
    assert "Information Technology" in note

    kept, note = drop_unreachable_floors(mk, [tech, bonds])  # FNB et titres: AAPL remplit le plancher
    assert tech in kept and note is None


def agent_mask(mk, constraints):
    """Ce que le moteur exclurait, d'après la requête que lui envoie le catalogue (mode d'instruments et symboles)."""
    request = agent_request(mk, constraints)
    allowed_types = INSTRUMENT_SELECTION[request["instrument_selection"]]
    return ~mk.assets["instrument_type"].isin(allowed_types) | mk.assets.index.isin(request["excluded_symbols"])
