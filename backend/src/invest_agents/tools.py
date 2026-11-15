"""Outils Strands exposés aux agents.

Chaque fabrique lie les outils à un contexte (contraintes, mandat, portefeuille) pour que le modèle
ne puisse pas modifier ce qui est imposé. Les outils retournent des chiffres calculés par du code;
les agents ne doivent citer que ces chiffres.

Le calcul vit dans `tool_core` (sans état). `gateway.run` l'exécute ici ou à travers AgentCore Gateway (MCP), selon
TOOLS_BACKEND: chaque closure y ajoute par le code le contexte imposé (contraintes, objectif, plafond de volatilité).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
from strands import tool

from . import factors, gateway
from .runtime import get_runtime_settings
from .catalog import DIMENSION_COLUMN, SHARE_TYPES, excluded_mask, share_members
from .market import Market
from .allocator import Objective, OptimizationResult
from .schemas import Constraint, ConstraintType as T, PortfolioMetrics


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
        return gateway.run("get_latest_macro_snapshot")

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
        return gateway.run("get_macro_history", country=country, metric=metric, start_date=start_date,
                           end_date=end_date, frequency=frequency, max_rows=max_rows)

    return [get_latest_macro_snapshot, get_macro_history]


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
    # Les contraintes du gestionnaire changent à chaque relance: on les lit dans `state` à chaque appel.

    def eligible_assets():
        """Univers admissible (pour screen_factor, calculé ici: les scores de facteurs restent dans le processus)."""
        hard = [c for c in state.constraints if c.hard]
        return market.assets[~excluded_mask(market, hard)]

    @tool
    def describe_universe() -> dict:
        """Résume l'univers d'investissement admissible (après exclusions imposées): nombre d'actifs par classe,
        secteur et pays, et fourchettes de volatilité et de rendement historiques."""
        return gateway.run("describe_universe", market=market, constraints=state.constraints)

    @tool
    def screen_assets(
        sector: Optional[str] = None,
        country: Optional[str] = None,
        asset_class: Optional[str] = None,
        max_volatility: Optional[float] = None,
        min_sharpe: Optional[float] = None,
        sort_by: str = "sharpe",
        limit: int = 20,
        theme: Optional[str] = None,
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
            theme: Étiquette de thématique à conserver, actions et FNB (ex. energie-propre, ia) (optionnel).
        """
        return gateway.run("screen_assets", market=market, constraints=state.constraints, sector=sector,
                           country=country, asset_class=asset_class, max_volatility=max_volatility,
                           min_sharpe=min_sharpe, sort_by=sort_by, limit=limit, **({"theme": theme} if theme else {}))

    @tool
    def screen_factor(
        factor: str,
        direction: str = "high",
        sector: Optional[str] = None,
        country: Optional[str] = None,
        max_volatility: Optional[float] = None,
        min_score: Optional[float] = None,
        sort_by: str = "score",
        limit: int = 20,
    ) -> dict:
        """Actions détenues en direct de l'univers admissible, avec leurs scores de facteurs (z-score dans leur
        secteur: 0 = moyenne du secteur, +1 = un écart-type mieux). Les FNB n'ont pas de score. Sers-t'en quand le
        profil contient min_factor_exposure ou max_factor_exposure: l'exposition du portefeuille est la moyenne des
        scores de ses actions, pondérée par leur poids, et au moins 10 % du portefeuille doit être en actions notées.
        Les actions les mieux notées sont souvent très volatiles: sous un plafond de volatilité, filtre par
        `min_score` (le seuil du profil) et trie par `ann_vol`.

        Args:
            factor: "momentum", "quality", "value", "growth" ou "small_cap" (petites capitalisations).
            direction: "high" pour les scores élevés (min_factor_exposure), "low" pour les bas (max_factor_exposure).
            sector: Secteur exact à conserver (optionnel).
            country: Pays exact à conserver (optionnel).
            max_volatility: Volatilité annualisée maximale d'une action, en fraction (0.25 = 25 %) (optionnel).
            min_score: Seuil de score à respecter: au moins ce score pour "high", au plus pour "low" (optionnel).
            sort_by: "score" (le plus extrême d'abord), "ann_vol" (le moins volatil d'abord) ou "sharpe".
            limit: Nombre maximal de résultats (max 50).
        """
        if factor not in factors.FACTORS:
            return {"error": f"Facteur inconnu: {factor!r}. Valeurs possibles: {', '.join(factors.FACTORS)}."}
        a = eligible_assets()
        if sector:
            a = a[a["sector"].str.lower() == sector.lower()]
        if country:
            a = a[a["country"].str.lower() == country.lower()]
        if max_volatility is not None:
            a = a[a["ann_vol"] <= max_volatility]
        scores = factors.scores_for(a.index)
        if min_score is not None and not scores.empty:
            scores = scores.loc[factors.meets(scores, [(factor, direction != "low", float(min_score))])]
        if scores.empty:
            return {"n_results": 0, "assets": [], "message": "Aucune action notée ne correspond à ces filtres."}
        if sort_by in ("ann_vol", "sharpe"):
            index = a.loc[scores.index].sort_values(sort_by, ascending=(sort_by == "ann_vol")).index
        else:
            index = scores[factor].sort_values(ascending=(direction == "low")).index
        order = pd.Index(index[: max(1, min(limit, 50))])
        rows = market._rows(a.loc[order])
        for row in rows:
            row["factor_scores"] = {f: round(float(scores.at[row["symbol"], f]), 2) for f in factors.FACTORS}
        return {"n_results": len(rows), "factor": factor, "assets": rows}

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
        raw = gateway.run("optimize_portfolio", market=market, symbols=list(symbols), objective=state.objective,
                          constraints=state.constraints, vol_cap=state.vol_cap, risk_aversion=state.risk_aversion)
        result = OptimizationResult(
            status=raw["status"], message=raw.get("message", ""), weights=dict(raw.get("weights") or {}),
            metrics=PortfolioMetrics.model_validate(raw["metrics"]) if raw.get("metrics") else None,
        )
        state.log.append(f"essai {state.attempts}: {result.status}")
        if result.ok:
            state.best = result
        out: dict = {"status": result.status, "message": result.message}
        if result.weights:
            out["weights"] = result.weights
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
        if result.weights:
            exposure, covered = factors.exposures(result.weights)
            if exposure:
                out["factor_exposure"] = {"by_factor": exposure, "scored_weight": covered}
        return out

    tools = [describe_universe, screen_assets, optimize_portfolio, *make_macro_tools()]
    if market.allowed_values()["factor"]:
        tools.insert(2, screen_factor)
    return tools


def fallback_selection(market: Market, constraints: list[Constraint], objective: Objective) -> list[str]:
    """Sélection de repli si le PM n'a produit aucun portefeuille valide (garde le pipeline en marche)."""
    hard = [c for c in constraints if c.hard]
    a = market.assets[~excluded_mask(market, hard)]
    n = min(15, get_runtime_settings().max_assets_per_portfolio)
    key, asc = ("ann_vol", True) if objective == "min_volatility" else ("sharpe", False)
    picks: list[str] = []
    # Un poids minimal (plancher d'obligations, crypto imposée…) exige des titres de son groupe, d'abord: sur l'univers
    # réel, les 15 meilleurs ratios de Sharpe sont tous des actions. 4 titres, pour tenir sous la limite de 40 %.
    for c in hard:
        column = DIMENSION_COLUMN.get(c.type.value.removeprefix("min_").removesuffix("_weight"))
        if c.type.value.startswith("min_") and c.target and column:
            group = a[a[column].astype(str).str.lower() == c.target.lower()]
            picks += group.sort_values(key, ascending=asc).index[:4].tolist()
        elif c.type in SHARE_TYPES and SHARE_TYPES[c.type][1] == "min" and c.target:  # une part: titres du groupe
            picks += a[share_members(a, c)].sort_values(key, ascending=asc).index[:4].tolist()
    # Contraintes de facteurs: des actions qui respectent tous les seuils à la fois, les moins volatiles d'abord.
    # Les mieux notées sont souvent très volatiles (sur l'univers réel, APP ou SNDK en qualité) et feraient
    # dépasser le plafond de volatilité.
    # Sous un plafond de volatilité, les actifs les plus calmes: sans eux, un profil prudent n'a aucune sélection valide.
    if any(c.type is T.MAX_VOLATILITY for c in hard):
        picks += a.sort_values("ann_vol").index[:10].tolist()
    fits = factor_fits(a, hard)
    picks += a.loc[fits].sort_values("ann_vol").index[:8].tolist()
    picks += a.loc[fits].sort_values("sharpe", ascending=False).index[:4].tolist()
    picks += a.sort_values(key, ascending=asc).head(n).index.tolist()
    return list(dict.fromkeys(picks))[: get_runtime_settings().max_assets_per_portfolio]


def factor_fits(eligible, hard: list[Constraint]) -> list[str]:
    """Actions admissibles qui respectent à elles seules toutes les contraintes de facteurs dures; [] sans contrainte."""
    scores = factors.scores_for(eligible.index)
    tilts = [c for c in hard if c.type in (T.MIN_FACTOR_EXPOSURE, T.MAX_FACTOR_EXPOSURE) and c.target in scores.columns]
    if not tilts:
        return []
    return factors.meets(scores, [(c.target, c.type is T.MIN_FACTOR_EXPOSURE, float(c.value or 0)) for c in tilts])
