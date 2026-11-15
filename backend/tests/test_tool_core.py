"""Les outils sans état (tool_core, publiés par le serveur MCP) et leur branchement dans les closures des agents."""

import json

import pytest

from invest_agents import gateway, tool_core
from invest_agents.allocator import optimize
from invest_agents.catalog import evaluate
from invest_agents.market import get_market
from invest_agents.schemas import Constraint
from invest_agents.tools import PMState, make_pm_tools


@pytest.fixture(scope="module")
def market():
    try:
        return get_market()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"dataset indisponible: {exc}")


@pytest.fixture
def constraints(market):
    sector = market.assets["sector"].value_counts().index[0]
    return [Constraint(type="exclude_sector", target=sector), Constraint(type="max_position_weight", value=0.25)]


def _symbols(market, constraints, n=10):
    return [a["symbol"] for a in tool_core.screen_assets(constraints, limit=n, market=market)["assets"]]


def test_optimize_matches_engine(market, constraints):
    symbols = _symbols(market, constraints)
    direct = optimize(market, symbols, "max_sharpe", constraints)
    out = tool_core.optimize_portfolio(symbols, "max_sharpe", [c.model_dump(mode="json") for c in constraints],
                                       market=market)
    assert out["status"] == direct.status
    assert out["weights"] == pytest.approx(direct.weights)
    assert out["metrics"]["volatility"] == pytest.approx(direct.metrics.volatility)
    json.dumps(out)  # sérialisable pour MCP


def test_check_matches_evaluate(market, constraints):
    symbols = _symbols(market, constraints, 6)
    weights = {s: 1 / len(symbols) for s in symbols}
    out = tool_core.check_portfolio_constraints(weights, [c.model_dump(mode="json") for c in constraints], market=market)
    expected = evaluate(market, weights, constraints)
    assert [c["passed"] for c in out["checks"]] == [c.passed for c in expected]


def test_screen_respects_exclusions(market, constraints):
    out = tool_core.screen_assets(constraints, limit=50, market=market)
    assert all(a["sector"] != constraints[0].target for a in out["assets"])


def test_pm_closure_injects_context_and_sets_best(market, constraints, monkeypatch):
    sent = {}

    def fake_remote(name, arguments):
        sent[name] = arguments
        return tool_core.optimize_portfolio(**arguments, market=market)

    monkeypatch.setenv("TOOLS_BACKEND", "gateway")
    monkeypatch.setenv("GATEWAY_URL", "https://example.invalid/mcp")
    monkeypatch.setattr(gateway, "call_remote", fake_remote)
    state = PMState(constraints=constraints, objective="min_volatility", vol_cap=0.2)
    tools = {t.tool_name: t for t in make_pm_tools(market, state)}
    out = tools["optimize_portfolio"](symbols=_symbols(market, constraints))
    args = sent["optimize_portfolio"]
    assert args["objective"] == "min_volatility" and args["vol_cap"] == 0.2
    assert args["constraints"][0]["target"] == constraints[0].target  # le contexte imposé est ajouté par le code
    assert out["status"] in ("optimal", "feasible") and state.best is not None
    assert state.best.metrics.volatility == pytest.approx(out["metrics"]["volatility"])


def test_gateway_failure_falls_back_to_local(market, constraints, monkeypatch):
    def broken(name, arguments):
        raise ConnectionError("gateway indisponible")

    monkeypatch.setenv("TOOLS_BACKEND", "gateway")
    monkeypatch.setenv("GATEWAY_URL", "https://example.invalid/mcp")
    monkeypatch.setattr(gateway, "call_remote", broken)
    out = gateway.run("describe_universe", market=market, constraints=constraints)
    assert out["n_assets"] == tool_core.describe_universe(constraints, market=market)["n_assets"]


def test_local_by_default(monkeypatch, market, constraints):
    monkeypatch.delenv("TOOLS_BACKEND", raising=False)
    monkeypatch.setattr(gateway, "call_remote", lambda *a: pytest.fail("pas d'appel à la Gateway"))
    assert gateway.run("describe_universe", market=market, constraints=constraints)["n_assets"] > 0


def test_parse_structured_and_text():
    assert gateway._parse({"status": "success", "structuredContent": {"result": {"a": 1}}}) == {"a": 1}
    assert gateway._parse({"status": "success", "content": [{"text": '{"b": 2}'}]}) == {"b": 2}
    with pytest.raises(RuntimeError):
        gateway._parse({"status": "error", "content": [{"text": "boom"}]})
