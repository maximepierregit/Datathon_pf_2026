"""Serveur MCP des outils MonPort, hébergé sur AgentCore Runtime (protocole MCP) derrière AgentCore Gateway.

AgentCore exige un serveur MCP en streamable HTTP sans état sur 0.0.0.0:8000/mcp. Les outils sont les fonctions sans
état de `invest_agents.tool_core`: le dataset (S3) est chargé une fois par microVM puis gardé en mémoire, ce qu'une
Lambda ne permettrait pas à chaque démarrage à froid.

En local: PORT=8000 python mcp_server/main.py (dans le zip du runtime, ce fichier devient main.py).
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
for candidate in (HERE / "src", HERE.parent / "src"):  # zip du runtime, ou dépôt
    if candidate.is_dir():
        sys.path.insert(0, str(candidate))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from invest_agents import tool_core  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

mcp = MCPServer(name="monport-tools", instructions=(
    "Outils financiers déterministes de MonPort: univers d'investissement, optimiseur de portefeuille sous "
    "contraintes, vérificateur de contraintes et contexte macro US/Canada. Les chiffres viennent du code."))

Constraints = list[dict[str, Any]]


@mcp.tool()
def describe_universe(constraints: Constraints) -> dict:
    """Résume l'univers admissible après les exclusions dures: nombre d'actifs par classe, secteur et pays, fourchettes
    de volatilité et de rendement historiques.

    Args:
        constraints: Contraintes du client (schéma Constraint: type, target, value, hard, source).
    """
    return tool_core.describe_universe(constraints)


@mcp.tool()
def screen_assets(constraints: Constraints, sector: Optional[str] = None, country: Optional[str] = None,
                  asset_class: Optional[str] = None, max_volatility: Optional[float] = None,
                  min_sharpe: Optional[float] = None, sort_by: str = "sharpe", limit: int = 20) -> dict:
    """Filtre l'univers admissible et retourne les meilleurs actifs selon un critère (sharpe, ann_return ou ann_vol).

    Args:
        constraints: Contraintes du client.
        sector: Secteur exact (optionnel).
        country: Pays exact (optionnel).
        asset_class: Classe d'actifs exacte (optionnel).
        max_volatility: Volatilité annualisée maximale d'un actif, en fraction.
        min_sharpe: Ratio de Sharpe historique minimal.
        sort_by: "sharpe", "ann_return" ou "ann_vol".
        limit: Nombre maximal de résultats (max 50).
    """
    return tool_core.screen_assets(constraints, sector, country, asset_class, max_volatility, min_sharpe, sort_by, limit)


@mcp.tool()
def optimize_portfolio(symbols: list[str], objective: str, constraints: Constraints, vol_cap: Optional[float] = None,
                       risk_aversion: Optional[float] = None) -> dict:
    """Calcule les poids optimaux d'une sélection en respectant toutes les contraintes dures (moteur SLSQP).

    Args:
        symbols: Symboles de la sélection (chaque titre pèse au moins 1 %).
        objective: "min_volatility", "max_sharpe", "max_return" ou "mean_variance".
        constraints: Contraintes du client.
        vol_cap: Plafond de volatilité du mandat, en fraction (optionnel).
        risk_aversion: Coefficient A de mean_variance, de 1 (audacieux) à 25 (prudent) (optionnel).
    """
    return tool_core.optimize_portfolio(symbols, objective, constraints, vol_cap, risk_aversion)


@mcp.tool()
def check_portfolio_constraints(weights: dict[str, float], constraints: Constraints) -> dict:
    """Vérifie un portefeuille contre chaque contrainte (dures et préférences): respectée ou non, valeur, limite.

    Args:
        weights: Poids par symbole (fractions qui somment à 1).
        constraints: Contraintes du client.
    """
    return tool_core.check_portfolio_constraints(weights, constraints)


@mcp.tool()
def get_latest_macro_snapshot() -> dict:
    """Dernière valeur de chaque série macro US et Canada (taux 10 ans et 2 ans, écart, taux directeur, inflation,
    chômage), avec ses z-scores sur 5 ans et sur tout l'historique."""
    return tool_core.get_latest_macro_snapshot()


@mcp.tool()
def get_macro_history(country: str = "", metric: str = "", start_date: str = "", end_date: str = "",
                      frequency: str = "monthly", max_rows: int = 600) -> dict:
    """Historique de la table macro, pour comparer des régimes passés avec le présent.

    Args:
        country: "US" ou "CA", vide pour les deux.
        metric: yield_10y, yield_2y, spread_10y_2y, policy_rate, inflation_yoy ou unemployment_rate; vide pour tous.
        start_date: AAAA-MM-JJ, vide pour le début.
        end_date: AAAA-MM-JJ, vide pour la fin.
        frequency: "monthly" ou "native".
        max_rows: Nombre maximal de lignes (au plus 1000).
    """
    return tool_core.get_macro_history(country, metric, start_date, end_date, frequency, max_rows)


if __name__ == "__main__":
    mcp.run("streamable-http", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), stateless_http=True,
            json_response=True)
