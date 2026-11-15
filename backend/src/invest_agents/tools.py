"""Outils Strands exposés aux agents.

Chaque fabrique lie les outils à un contexte (contraintes, mandat, portefeuille) pour que le modèle
ne puisse pas modifier ce qui est imposé. Les outils retournent des chiffres calculés par du code;
les agents ne doivent citer que ces chiffres.

Pour exposer ces outils via AgentCore Gateway (MCP), il suffit de déplacer les fonctions pures
(`optimize`, `evaluate`, `Market.*`) derrière une Lambda. Les signatures ne changent pas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from strands import tool

from .config import get_settings
from .constraints import evaluate, excluded_mask
from .data import Market
from .optimizer import Objective, OptimizationResult, optimize
from .schemas import Constraint


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def make_extraction_tools(market: Market) -> list:
    @tool
    def search_universe(query: str) -> dict:
        """Cherche un titre dans l'univers par nom d'entreprise ou par symbole.

        Args:
            query: Nom de l'entreprise (ex. "Apple") ou début de symbole.
        """
        return {"matches": market.search(query, limit=8)}

    return [search_universe]


# --------------------------------------------------------------------------- #
# Gestionnaire de portefeuille
# --------------------------------------------------------------------------- #
@dataclass
class PMState:
    constraints: list[Constraint]
    objective: Objective
    vol_cap: Optional[float]
    risk_aversion: Optional[float] = None  # coefficient A, pour l'objectif mean_variance
    best: Optional[OptimizationResult] = None
    attempts: int = 0
    log: list[str] = field(default_factory=list)


def make_pm_tools(market: Market, state: PMState) -> list:
    hard = [c for c in state.constraints if c.hard]
    eligible = market.assets[~excluded_mask(market, hard)]

    @tool
    def describe_universe() -> dict:
        """Résume l'univers d'investissement admissible (après exclusions imposées): nombre d'actifs par classe,
        secteur et pays, et fourchettes de volatilité historique et de rendement espéré."""
        a = eligible
        return {
            "n_assets": int(len(a)),
            "by_asset_class": a["asset_class"].value_counts().to_dict(),
            "by_sector": a["sector"].value_counts().to_dict(),
            "by_country": a["country"].value_counts().to_dict(),
            "ann_vol_range": [round(float(a["ann_vol"].min()), 3), round(float(a["ann_vol"].max()), 3)],
            "ann_return_range": [round(float(a["ann_return"].min()), 3), round(float(a["ann_return"].max()), 3)],
        }

    @tool
    def screen_assets(
        sector: Optional[str] = None,
        country: Optional[str] = None,
        asset_class: Optional[str] = None,
        max_volatility: Optional[float] = None,
        min_sharpe: Optional[float] = None,
        sort_by: str = "sharpe",
        limit: int = 20,
    ) -> dict:
        """Filtre l'univers admissible et retourne les meilleurs actifs selon un critère.

        Args:
            sector: Secteur exact à conserver (optionnel).
            country: Pays exact à conserver (optionnel).
            asset_class: Classe d'actifs exacte (ex. Equity, Fixed Income, Crypto) (optionnel).
            max_volatility: Volatilité annualisée maximale d'un actif, en fraction (0.25 = 25 %).
            min_sharpe: Ratio de Sharpe minimal (rendement espéré, volatilité historique).
            sort_by: Critère de tri: "sharpe", "ann_return" ou "ann_vol" (croissant pour ann_vol).
            limit: Nombre maximal de résultats (max 50).
        """
        a = eligible
        if sector:
            a = a[a["sector"].str.lower() == sector.lower()]
        if country:
            a = a[a["country"].str.lower() == country.lower()]
        if asset_class:
            a = a[a["asset_class"].str.lower() == asset_class.lower()]
        if max_volatility is not None:
            a = a[a["ann_vol"] <= max_volatility]
        if min_sharpe is not None:
            a = a[a["sharpe"] >= min_sharpe]
        key = sort_by if sort_by in ("sharpe", "ann_return", "ann_vol") else "sharpe"
        a = a.sort_values(key, ascending=(key == "ann_vol")).head(max(1, min(limit, 50)))
        return {"n_results": int(len(a)), "assets": market._rows(a)}

    @tool
    def optimize_portfolio(symbols: list[str]) -> dict:
        """Calcule les poids optimaux pour une sélection de titres, selon l'objectif de ton mandat et en
        respectant toutes les contraintes dures de l'utilisateur. Le dernier appel réussi devient ton portefeuille.

        Args:
            symbols: Liste de symboles (ex. ["AAPL", "RY.TO"]). Chaque titre pèse au moins 1 %.
        """
        state.attempts += 1
        result = optimize(market, symbols, state.objective, state.constraints, vol_cap=state.vol_cap,
                          risk_aversion=state.risk_aversion)
        state.log.append(f"essai {state.attempts}: {result.status}")
        if result.ok:
            state.best = result
        out: dict = {"status": result.status, "message": result.message}
        if result.weights:
            out["weights"] = {s: w for s, w in sorted(result.weights.items(), key=lambda kv: -kv[1])}
        if result.metrics:
            m = result.metrics
            out["metrics"] = {
                "expected_return": m.expected_return,
                "volatility": m.volatility,
                "sharpe": m.sharpe,
                "max_drawdown": m.max_drawdown,
                "n_positions": m.n_positions,
                "sector_weights": m.sector_weights,
                "country_weights": m.country_weights,
                "asset_class_weights": m.asset_class_weights,
            }
        return out

    return [describe_universe, screen_assets, optimize_portfolio]


def fallback_selection(market: Market, constraints: list[Constraint], objective: Objective) -> list[str]:
    """Sélection de repli si le PM n'a produit aucun portefeuille valide (garde le pipeline en marche)."""
    hard = [c for c in constraints if c.hard]
    a = market.assets[~excluded_mask(market, hard)]
    n = min(15, get_settings().max_assets_per_portfolio)
    key, asc = ("ann_vol", True) if objective == "min_volatility" else ("sharpe", False)
    return a.sort_values(key, ascending=asc).head(n).index.tolist()


# --------------------------------------------------------------------------- #
# Juge
# --------------------------------------------------------------------------- #
def make_judge_tools(market: Market, weights: dict[str, float], constraints: list[Constraint]) -> list:
    @tool
    def check_portfolio_constraints() -> dict:
        """Vérifie le portefeuille évalué contre chaque contrainte de l'utilisateur (dures et préférences).
        Retourne, pour chacune, si elle est respectée, la valeur observée et la limite."""
        checks = evaluate(market, weights, constraints)
        return {
            "all_hard_respected": all(c.passed for c in checks if c.constraint.hard),
            "checks": [
                {
                    "label": c.label,
                    "hard": c.constraint.hard,
                    "passed": c.passed,
                    "actual": c.actual,
                    "limit": c.limit,
                }
                for c in checks
            ],
        }

    return [check_portfolio_constraints]
