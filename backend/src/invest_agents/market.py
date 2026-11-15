"""Marché: catalogue d'actifs, rendements espérés et covariance, au-dessus de `data.py`.

`data.py` charge et valide le Parquet, puis fournit les matrices de rendements sans rien estimer.
Ce module estime mu et Sigma exactement comme `config.py` le prescrit:
- mu: méthode choisie par `config.get_return_method` (historical, ewma, capm_shrinkage, capm_benchmark_shrinkage);
- Sigma: Ledoit-Wolf (cible identité mise à l'échelle) ou covariance d'échantillon, sur les observations
  complètes de la sélection.
Aucun rendement manquant n'est fabriqué (ni zéro, ni report de la veille).
"""
from __future__ import annotations
import difflib
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

from .config import get_capm_benchmark, get_return_method, get_settings
from .data import OptimizerData, prepare_optimizer_data
from .factors import available_factors
from .schemas import PortfolioMetrics

logger = logging.getLogger(__name__)

UNKNOWN = "Non classé"
META_COLUMNS = ["name", "sector", "industry", "country", "currency", "asset_class", "instrument_type", "market"]


# --------------------------------------------------------------------------- #
# Rendements espérés (annualisés, en CAD)
# --------------------------------------------------------------------------- #
def _tail(series: pd.Series, lookback: Optional[int]) -> pd.Series:
    """Dernières `lookback` observations disponibles d'un symbole (None = tout l'historique)."""
    observed = series.dropna()
    return observed if lookback is None else observed.iloc[-int(lookback):]


def _historical_mu(series: pd.Series, lookback: Optional[int], min_obs: int, periods: int) -> float:
    window = _tail(series, lookback)
    if len(window) < min_obs:
        raise ValueError(f"Historique insuffisant pour {series.name}: {len(window)} observations (minimum {min_obs}).")
    return float(window.mean() * periods)


def _ewma_mu(series: pd.Series, params: Mapping[str, Any], periods: int) -> float:
    window = _tail(series, params["lookback_observations"])
    if len(window) < params["min_observations"]:
        raise ValueError(
            f"Historique insuffisant pour {series.name}: {len(window)} observations (minimum {params['min_observations']})."
        )
    age = np.arange(len(window) - 1, -1, -1)
    weights = 0.5 ** (age / params["half_life_observations"])
    return float(np.average(window.to_numpy(dtype=float), weights=weights) * periods)


def _beta(series: pd.Series, reference: pd.Series, lookback: Optional[int], min_paired: int) -> Optional[float]:
    """Bêta sur les dates communes ; None si l'historique commun est trop court."""
    paired = pd.DataFrame({"asset": series, "ref": reference}).dropna()
    if lookback is not None:
        paired = paired.iloc[-int(lookback):]
    if len(paired) < min_paired:
        return None
    variance = paired["ref"].var()
    if not variance > 0:
        return None
    return float(paired["asset"].cov(paired["ref"]) / variance)


def estimate_expected_returns(returns: pd.DataFrame, meta: pd.DataFrame, settings: Mapping[str, Any]) -> pd.DataFrame:
    """mu annualisé par symbole (colonne `mu`) et méthode réellement utilisée (colonne `method`)."""
    est = settings["estimation"]
    periods = est["periods_per_year"]
    hist = est["historical"]
    available = set(returns.columns)
    rows: dict[str, tuple[float, str]] = {}
    for symbol in returns.columns:
        series = returns[symbol]
        method = get_return_method(
            meta.at[symbol, "asset_class"], meta.at[symbol, "instrument_type"], symbol=symbol, settings=settings
        )
        used = method
        if method == "historical":
            mu = _historical_mu(series, hist["lookback_observations"], hist["min_observations"], periods)
        elif method == "ewma":
            mu = _ewma_mu(series, est["ewma"], periods)
        else:
            if method == "capm_shrinkage":
                p = est["capm_shrinkage"]
                reference_symbol = p["market_proxy"]
                premium = p["erp_annual"]
            else:  # capm_benchmark_shrinkage: ni benchmark ni prime ne sont devinés
                p = est["capm_benchmark_shrinkage"]
                reference_symbol = get_capm_benchmark(
                    symbol, meta.loc[symbol], available_symbols=available, settings=settings
                )
                if reference_symbol is None:
                    raise ValueError(f"Aucun benchmark CAPM configuré pour {symbol}.")
                premium = p["erp_annual_by_benchmark"].get(reference_symbol)
                if premium is None:
                    raise ValueError(f"Prime de risque absente pour le benchmark {reference_symbol} ({symbol}).")
            if reference_symbol not in available:
                raise ValueError(f"Référence CAPM {reference_symbol} absente de l'univers (pour {symbol}).")
            beta = _beta(series, returns[reference_symbol], p["lookback_observations"], p["min_paired_observations"])
            historical = _historical_mu(series, p["historical_lookback_observations"], hist["min_observations"], periods)
            if beta is None:
                logger.warning("%s: historique commun avec %s insuffisant, repli sur la méthode historique",
                               symbol, reference_symbol)
                mu, used = historical, "historical_fallback"
            else:
                target = p["rf_annual"] + beta * premium
                mu = p["alpha"] * target + (1 - p["alpha"]) * historical
        rows[symbol] = (mu, used)
    return pd.DataFrame.from_dict(rows, orient="index", columns=["mu", "method"])


# --------------------------------------------------------------------------- #
# Covariance (annualisée)
# --------------------------------------------------------------------------- #
def joint_window(returns: pd.DataFrame, cov_cfg: Mapping[str, Any]) -> pd.DataFrame:
    """Observations complètes de la sélection (aucun rendement comblé), sur la fenêtre de covariance."""
    window = returns.dropna()
    lookback = cov_cfg["lookback_observations"]
    if lookback is not None:
        window = window.iloc[-int(lookback):]
    if len(window) < cov_cfg["min_joint_observations"]:
        shortest = returns.count().nsmallest(3)
        detail = ", ".join(f"{s} ({n} obs)" for s, n in shortest.items())
        raise ValueError(
            f"Historique commun insuffisant: {len(window)} dates complètes pour {returns.shape[1]} titres "
            f"(minimum {cov_cfg['min_joint_observations']}). Titres à l'historique le plus court: {detail}."
        )
    return window


def _ledoit_wolf(x: np.ndarray, assume_centered: bool = False) -> np.ndarray:
    """Covariance Ledoit-Wolf, cible mu·I (même formule que sklearn.covariance.LedoitWolf)."""
    n, p = x.shape
    centered = x if assume_centered else x - x.mean(axis=0)
    sample = centered.T @ centered / n
    if p == 1:
        return sample
    trace = float(np.trace(sample))
    mu = trace / p
    squared = centered**2
    delta_ = float(((centered.T @ centered) ** 2).sum()) / n**2
    beta_ = float((squared.T @ squared).sum())
    beta = (beta_ / n - delta_) / (p * n)
    delta = (delta_ - 2.0 * mu * trace + p * mu**2) / p
    beta = min(beta, delta)
    shrinkage = 0.0 if beta == 0 else beta / delta
    return (1 - shrinkage) * sample + shrinkage * mu * np.eye(p)


def estimate_covariance(returns: pd.DataFrame, settings: Mapping[str, Any]) -> np.ndarray:
    """Matrice de covariance annualisée des colonnes de `returns`, dans l'ordre des colonnes."""
    cov_cfg = settings["covariance"]
    periods = cov_cfg["periods_per_year"]
    method = cov_cfg["method"]
    if method == "ledoit_wolf":
        window = joint_window(returns, cov_cfg)
        lw = cov_cfg["ledoit_wolf"]
        daily = _ledoit_wolf(window.to_numpy(dtype=float), assume_centered=lw["assume_centered"])
    elif method == "sample":
        sample = cov_cfg["sample"]
        lookback = cov_cfg["lookback_observations"]
        window = returns if lookback is None else returns.iloc[-int(lookback):]
        matrix = window.cov(min_periods=sample["min_pairwise_observations"])
        if matrix.isna().any().any():
            raise ValueError("Covariance d'échantillon incomplète: des paires de titres ont trop peu de dates communes.")
        daily = matrix.to_numpy(dtype=float)
        if sample["repair_psd"]:
            values, vectors = np.linalg.eigh((daily + daily.T) / 2)
            daily = (vectors * np.clip(values, sample["eigenvalue_floor"], None)) @ vectors.T
    else:
        raise ValueError(f"Méthode de covariance inconnue : {method!r}")
    cov = daily * periods
    return (cov + cov.T) / 2


# --------------------------------------------------------------------------- #
# Marché
# --------------------------------------------------------------------------- #
@dataclass
class Market:
    assets: pd.DataFrame  # index = symbol ; métadonnées + ann_return (mu de config), ann_vol, sharpe, n_obs
    returns: pd.DataFrame  # date x symbol, rendements quotidiens en CAD, NaN structurels conservés
    settings: dict[str, Any]  # instantané de config.get_settings()

    @property
    def risk_free_rate(self) -> float:
        return float(self.settings["estimation"]["capm_shrinkage"]["rf_annual"])

    # ------------------------------------------------------------------ #
    # Catalogue
    # ------------------------------------------------------------------ #
    def allowed_values(self) -> dict[str, list[str]]:
        a = self.assets
        return {
            "sector": sorted(a["sector"].dropna().unique().tolist()),
            "country": sorted(a["country"].dropna().unique().tolist()),
            "asset_class": sorted(a["asset_class"].dropna().unique().tolist()),
            "instrument_type": sorted(a["instrument_type"].dropna().astype(str).unique().tolist()),
            "symbol": sorted(a.index.tolist()),
            "factor": available_factors(a.index),
        }

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Recherche par symbole ou nom d'entreprise (insensible à la casse, tolérante aux fautes)."""
        q = query.strip().lower()
        if not q:
            return []
        a = self.assets
        sym = a.index.str.lower()
        names = a["name"].fillna("").str.lower()
        mask = (sym == q) | names.str.contains(q, regex=False) | sym.str.startswith(q)
        hits = a[mask]
        if hits.empty:
            close = difflib.get_close_matches(q, names.tolist() + sym.tolist(), n=limit, cutoff=0.6)
            hits = a[names.isin(close) | sym.isin(close)]
        return self._rows(hits.head(limit))

    def _rows(self, df: pd.DataFrame) -> list[dict]:
        out = []
        for symbol, r in df.iterrows():
            out.append(
                {
                    "symbol": symbol,
                    "name": r["name"],
                    "sector": r["sector"],
                    "country": r["country"],
                    "asset_class": r["asset_class"],
                    "ann_return": round(float(r["ann_return"]), 4),
                    "ann_vol": round(float(r["ann_vol"]), 4),
                    "sharpe": round(float(r["sharpe"]), 3),
                }
            )
        return out

    # ------------------------------------------------------------------ #
    # Moments statistiques
    # ------------------------------------------------------------------ #
    def moments(self, symbols: list[str]) -> tuple[np.ndarray, np.ndarray]:
        """Rendements espérés et covariance annualisés d'une sélection (ValueError si l'historique commun manque)."""
        unknown = [s for s in symbols if s not in self.assets.index]
        if unknown:
            raise ValueError(f"Symboles absents de l'univers: {', '.join(unknown)}")
        mu = self.assets.loc[symbols, "ann_return"].to_numpy(dtype=float)
        cov = estimate_covariance(self.returns[symbols], self.settings)
        return mu, cov

    def portfolio_metrics(self, weights: dict[str, float]) -> PortfolioMetrics:
        symbols = [s for s, w in weights.items() if w > 0]
        w = np.array([weights[s] for s in symbols], dtype=float)
        w = w / w.sum()
        mu, cov = self.moments(symbols)
        ret = float(mu @ w)
        vol = float(np.sqrt(max(w @ cov @ w, 0.0)))
        rf = self.risk_free_rate
        window = joint_window(self.returns[symbols], self.settings["covariance"])
        curve = np.cumprod(1 + window.to_numpy(dtype=float) @ w)
        drawdown = float((curve / np.maximum.accumulate(curve) - 1).min())
        hhi = float((w**2).sum())
        a = self.assets.loc[symbols]

        def group(col: str) -> dict[str, float]:
            g = pd.Series(w, index=symbols).groupby(a[col].fillna(UNKNOWN)).sum()
            return {k: round(float(v), 4) for k, v in g.sort_values(ascending=False).items()}

        return PortfolioMetrics(
            expected_return=round(ret, 4),
            volatility=round(vol, 4),
            sharpe=round((ret - rf) / vol, 3) if vol > 0 else 0.0,
            max_drawdown=round(drawdown, 4),
            n_positions=len(symbols),
            hhi=round(hhi, 4),
            effective_n=round(1 / hhi, 1),
            sector_weights=group("sector"),
            country_weights=group("country"),
            asset_class_weights=group("asset_class"),
        )


def build_market(data: OptimizerData, settings: Mapping[str, Any]) -> Market:
    """Construit un `Market` à partir des entrées préparées par `data.prepare_optimizer_data`."""
    returns = data.returns
    meta = data.eligible_universe.reindex(index=returns.columns, columns=META_COLUMNS).copy()
    for col in META_COLUMNS:
        meta[col] = meta[col].astype(object).mask(meta[col].isna(), np.nan)
    meta["name"] = meta["name"].fillna(pd.Series(meta.index, index=meta.index))
    for col in ("sector", "country", "asset_class", "instrument_type"):
        meta[col] = meta[col].fillna(UNKNOWN).astype(str)

    periods = settings["estimation"]["periods_per_year"]
    lookback = settings["covariance"]["lookback_observations"]
    rf = float(settings["estimation"]["capm_shrinkage"]["rf_annual"])
    expected = estimate_expected_returns(returns, meta, settings)
    ann_vol = returns.apply(lambda s: _tail(s, lookback).std()) * np.sqrt(periods)
    stats = pd.DataFrame(
        {
            "ann_return": expected["mu"],
            "ann_vol": ann_vol,
            "sharpe": (expected["mu"] - rf) / ann_vol.replace(0, np.nan),
            "n_obs": returns.count(),
        }
    ).fillna(0.0)
    stats["return_method"] = expected["method"]
    assets = meta.join(stats)
    logger.info("Marché construit: %d actifs, %d dates", len(assets), len(returns))
    return Market(assets=assets, returns=returns, settings=dict(settings))


@lru_cache(maxsize=1)
def get_market() -> Market:
    """Charge le Parquet défini dans config.py (local ou s3://) et construit le marché, une seule fois."""
    settings = get_settings()
    d = settings["data"]
    data = prepare_optimizer_data(
        d["parquet_source"],
        as_of=d["as_of"],
        start_date=d["start_date"],
        min_observations=d["min_observations"],
        strict_validation=d["strict_validation"],
        region_overrides=d["region_overrides"] or None,
    )
    return build_market(data, settings)  # `data` (panel complet) est libéré au retour
