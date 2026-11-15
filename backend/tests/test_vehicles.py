"""« FNB seulement » écarte les titres détenus en direct, pas les FNB de la même classe d'actifs."""

from types import SimpleNamespace

import pandas as pd

from invest_agents.catalog import agent_request, evaluate
from invest_agents.monport import preference_constraints
from invest_agents.schemas import ConstraintType as T


def market():
    """Comme l'univers réel: un FNB d'actions a la classe « Equity », comme une action."""
    rows = [
        ("AAPL", "Equity", "Stock"),
        ("RY.TO", "Equity", "Stock"),
        ("SPY", "Equity", "ETF"),
        ("XBB.TO", "Fixed Income", "ETF"),
        ("GLD", "Alternative", "ETF"),
        ("BTC-CAD", "Alternative", "Cryptocurrency"),
    ]
    assets = pd.DataFrame(rows, columns=["symbol", "asset_class", "instrument_type"]).set_index("symbol")

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
    mk, allowed = market()
    request = agent_request(mk, fnb_only(allowed))
    assert set(request["excluded_symbols"]) == {"AAPL", "RY.TO", "BTC-CAD"}
    assert request["excluded_asset_classes"] == []


def test_fnb_only_flags_a_direct_stock():
    mk, allowed = market()
    checks = evaluate(mk, {"SPY": 0.6, "AAPL": 0.4}, fnb_only(allowed))
    assert [c.constraint.target for c in checks if not c.passed] == ["Stock"]


def test_all_vehicles_excludes_nothing():
    _, allowed = market()
    out, _ = preference_constraints({"vehicles": "tous"}, allowed)
    assert out == []
