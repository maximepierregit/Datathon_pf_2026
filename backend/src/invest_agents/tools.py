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

from .runtime import get_runtime_settings
from .catalog import evaluate, excluded_mask
from .macro import get_macro, history, latest_snapshot
from .market import Market
from .allocator import Objective, OptimizationResult, optimize
from .schemas import Constraint


# --------------------------------------------------------------------------- #
# Contexte macro (gestionnaires, agents Risque, juge)
# --------------------------------------------------------------------------- #
MACRO_PROMPT = """CONTEXTE MACRO (États-Unis et Canada)
`get_latest_macro_snapshot` donne la dernière valeur de chaque série (taux 10 ans et 2 ans, écart 10 ans-2 ans, taux
directeur, inflation sur un an, chômage) avec ses z-scores. `get_macro_history` donne l'historique, pour comparer le
régime actuel à des régimes passés. Commence par le premier; n'appelle le second que s'il éclaire ta décision.
- Précise la fenêtre de chaque z-score cité: `z_5y` (5 ans glissants) ou `z_full` (tout l'historique).
- Tiens compte de `days_stale` et de `ref_period`: l'inflation et le chômage décrivent un mois passé.
- Le contexte macro éclaire ton analyse. Il ne change ni les contraintes du client ni les chiffres calculés par le code,
  et il ne prédit rien: présente une direction possible comme une hypothèse.
- Si l'outil retourne une erreur, poursuis sans contexte macro et ne l'invente pas."""


def make_macro_tools() -> list:
    """Outils en lecture seule sur la table macro. Une source indisponible donne une erreur lisible, pas un plantage."""

    @tool
    def get_latest_macro_snapshot() -> dict:
        """Dernière valeur de chaque pays (US, CA) et indicateur (yield_10y, yield_2y, spread_10y_2y, policy_rate,
        inflation_yoy, unemployment_rate), en %. Chaque ligne donne metric_value, z_5y (z-score sur 5 ans glissants),
        z_full (z-score sur tout l'historique), history_start_date, ref_period (période décrite par la valeur) et
        days_stale (jours entre cette ligne et la date la plus récente du fichier). À appeler en premier pour situer
        le régime macro actuel."""
        try:
            return latest_snapshot(get_macro())
        except Exception as exc:  # noqa: BLE001  (S3 inaccessible, fichier absent...)
            return {"error": f"Contexte macro indisponible: {exc}"}

    @tool
    def get_macro_history(
        country: str = "",
        metric: str = "",
        start_date: str = "",
        end_date: str = "",
        frequency: str = "monthly",
        max_rows: int = 600,
    ) -> dict:
        """Historique de la table macro, pour comparer des régimes passés avec le présent.

        Args:
            country: "US" ou "CA". Vide pour les deux.
            metric: yield_10y, yield_2y, spread_10y_2y, policy_rate, inflation_yoy ou unemployment_rate. Vide pour tous.
            start_date: Borne inférieure incluse, AAAA-MM-JJ. Vide pour le début des données.
            end_date: Borne supérieure incluse, AAAA-MM-JJ. Vide pour la fin des données.
            frequency: "monthly" (dernière valeur de chaque mois, recommandé) ou "native" (quotidien pour les taux,
                mensuel pour l'inflation et le chômage).
            max_rows: Nombre maximal de lignes (au plus 1000). Au-delà, les lignes les plus récentes sont retournées.
        """
        try:
            return history(get_macro(), country, metric, start_date, end_date, frequency, max_rows)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Historique macro indisponible: {exc}"}

    return [get_latest_macro_snapshot, get_macro_history]


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
    # True quand on interroge le gestionnaire après coup: il explique son portefeuille, il ne le modifie plus.
    read_only: bool = False


def make_pm_tools(market: Market, state: PMState) -> list:
    def eligible_assets():
        """Univers admissible. Recalculé à chaque appel: les contraintes du gestionnaire changent à chaque relance."""
        hard = [c for c in state.constraints if c.hard]
        return market.assets[~excluded_mask(market, hard)]

    @tool
    def describe_universe() -> dict:
        """Résume l'univers d'investissement admissible (après exclusions imposées): nombre d'actifs par classe,
        secteur et pays, et fourchettes de volatilité et de rendement historiques."""
        a = eligible_assets()
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
            min_sharpe: Ratio de Sharpe historique minimal.
            sort_by: Critère de tri: "sharpe", "ann_return" ou "ann_vol" (croissant pour ann_vol).
            limit: Nombre maximal de résultats (max 50).
        """
        a = eligible_assets()
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
        if state.read_only:
            return {"status": "read_only", "message": "Le portefeuille est figé: explique-le, ne le recalcule pas."}
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

    return [describe_universe, screen_assets, optimize_portfolio, *make_macro_tools()]


def fallback_selection(market: Market, constraints: list[Constraint], objective: Objective) -> list[str]:
    """Sélection de repli si le PM n'a produit aucun portefeuille valide (garde le pipeline en marche)."""
    hard = [c for c in constraints if c.hard]
    a = market.assets[~excluded_mask(market, hard)]
    n = min(15, get_runtime_settings().max_assets_per_portfolio)
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

    return [check_portfolio_constraints, *make_macro_tools()]
