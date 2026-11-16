"""Outils métier sans état: les fonctions que publie le serveur MCP (mcp_server/main.py, derrière AgentCore Gateway).

Chaque fonction reçoit tout son contexte en paramètres JSON (contraintes, objectif, plafond) et retourne un dict JSON.
Les closures de `tools.py` gardent la signature vue par le modèle et ajoutent ce contexte par le code: le modèle ne
peut donc ni changer ni contourner une contrainte, que l'outil tourne dans le processus ou derrière la Gateway.
"""

from __future__ import annotations

from typing import Any, Optional

from .allocator import optimize
from .catalog import evaluate, excluded_mask, members
from .macro import get_macro, history, latest_snapshot
from .market import Market, get_market
from .schemas import Constraint


def _constraints(raw: list[Any]) -> list[Constraint]:
    return [c if isinstance(c, Constraint) else Constraint.model_validate(c) for c in raw or []]


def _eligible(market: Market, constraints: list[Constraint]):
    hard = [c for c in constraints if c.hard]
    return market.assets[~excluded_mask(market, hard)]


def describe_universe(constraints: list[Any], market: Optional[Market] = None) -> dict:
    """Univers admissible après les exclusions dures: comptes par classe, secteur, pays, fourchettes de risque."""
    a = _eligible(market or get_market(), _constraints(constraints))
    return {
        "n_assets": int(len(a)),
        "by_asset_class": a["asset_class"].value_counts().to_dict(),
        "by_sector": a["sector"].value_counts().to_dict(),
        "by_country": a["country"].value_counts().to_dict(),
        "ann_vol_range": [round(float(a["ann_vol"].min()), 3), round(float(a["ann_vol"].max()), 3)],
        "ann_return_range": [round(float(a["ann_return"].min()), 3), round(float(a["ann_return"].max()), 3)],
    }


def screen_assets(
    constraints: list[Any],
    sector: Optional[str] = None,
    country: Optional[str] = None,
    asset_class: Optional[str] = None,
    max_volatility: Optional[float] = None,
    min_sharpe: Optional[float] = None,
    sort_by: str = "sharpe",
    limit: int = 20,
    market: Optional[Market] = None,
    theme: Optional[str] = None,
) -> dict:
    """Filtre l'univers admissible et retourne les meilleurs actifs selon un critère."""
    market = market or get_market()
    a = _eligible(market, _constraints(constraints))
    if sector:
        a = a[a["sector"].str.lower() == sector.lower()]
    if theme:
        a = a[members(a, "theme", [theme])]
    if country:
        a = a[a["country"].str.lower() == country.lower()]
    if asset_class:
        a = a[a["asset_class"].str.lower() == asset_class.lower()]
    if max_volatility is not None:
        a = a[a["ann_vol"] <= max_volatility]
    if min_sharpe is not None:
        a = a[a["sharpe"] >= min_sharpe]
    key = sort_by if sort_by in ("sharpe", "ann_return", "ann_vol") else "sharpe"
    a = a.sort_values(key, ascending=(key == "ann_vol")).head(max(1, min(int(limit), 50)))
    return {"n_results": int(len(a)), "assets": market._rows(a)}


def optimize_portfolio(
    symbols: list[str],
    objective: str,
    constraints: list[Any],
    vol_cap: Optional[float] = None,
    risk_aversion: Optional[float] = None,
    market: Optional[Market] = None,
) -> dict:
    """Poids optimaux d'une sélection sous contraintes. `metrics` est complet (PortfolioMetrics)."""
    result = optimize(market or get_market(), list(symbols), objective, _constraints(constraints),  # type: ignore[arg-type]
                      vol_cap=vol_cap, risk_aversion=risk_aversion)
    out: dict = {"status": result.status, "message": result.message}
    if result.weights:
        out["weights"] = {s: w for s, w in sorted(result.weights.items(), key=lambda kv: -kv[1])}
    if result.metrics:
        out["metrics"] = result.metrics.model_dump(mode="json")
    return out


def check_portfolio_constraints(weights: dict[str, float], constraints: list[Any],
                                market: Optional[Market] = None) -> dict:
    """Vérifie un portefeuille contre chaque contrainte (dures et préférences), calculé par le code."""
    checks = evaluate(market or get_market(), {k: float(v) for k, v in weights.items()}, _constraints(constraints))
    return {
        "all_hard_respected": all(c.passed for c in checks if c.constraint.hard),
        "checks": [{"label": c.label, "hard": c.constraint.hard, "passed": c.passed, "actual": c.actual,
                    "limit": c.limit} for c in checks],
    }


def get_latest_macro_snapshot() -> dict:
    try:
        return latest_snapshot(get_macro())
    except Exception as exc:  # noqa: BLE001  (S3 inaccessible, fichier absent...)
        return {"error": f"Contexte macro indisponible: {exc}"}


def get_macro_history(country: str = "", metric: str = "", start_date: str = "", end_date: str = "",
                      frequency: str = "monthly", max_rows: int = 600) -> dict:
    try:
        return history(get_macro(), country, metric, start_date, end_date, frequency, max_rows)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Historique macro indisponible: {exc}"}
