"""Chargement du dataset fixe et calculs de marché (rendements, covariance, métriques)."""

from __future__ import annotations

import difflib
import logging
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .classify import CLASS_PRIOR_MU, CASH_NAME, CASH_SYMBOL, NO_REGION, SEP, WORLD, cash_series, classify
from .config import get_settings
from .schemas import PortfolioMetrics

logger = logging.getLogger(__name__)

TRADING_DAYS = 252
MIN_OBSERVATIONS = 120
UNKNOWN = "Non classé"

# Colonnes produites par `create_opt_inputs` dans Universe_Cleaned.ipynb
REQUIRED_COLUMNS = {"date", "symbol", "total_return_cad"}
META_COLUMNS = ["name", "sector", "industry", "country", "currency", "asset_class", "instrument_type", "market",
                "category_group", "category", "market_cap", "expense_ratio",
                "theme"]  # `theme`: identifiants séparés par « ; » (data-prep/build_universe.py)
# Dimension de contrainte -> colonne de `Market.assets`. `theme` et `factor` sont des ensembles encodés "|a|b|".
DIMENSION_COLUMN = {"sector": "sector", "country": "country", "asset_class": "asset_class", "region": "region",
                    "instrument_type": "instrument_type", "theme": "themes", "factor": "factors"}
SET_DIMENSIONS = {"theme", "factor"}
NOT_A_GROUP = {UNKNOWN, NO_REGION, WORLD, ""}


def _resolve_path(path: str) -> str:
    """Télécharge le fichier si c'est une URI S3, sinon retourne le chemin local."""
    if not path.startswith("s3://"):
        return path
    import boto3

    bucket, _, key = path[len("s3://") :].partition("/")
    target = Path(tempfile.gettempdir()) / f"dataset-{Path(key).name}"
    if not target.exists():
        logger.info("Téléchargement du dataset depuis %s", path)
        boto3.client("s3").download_file(bucket, key, str(target))
    return str(target)


@dataclass
class Market:
    assets: pd.DataFrame  # index = symbol
    returns: pd.DataFrame  # date x symbol, rendements quotidiens en CAD

    # ------------------------------------------------------------------ #
    # Catalogue
    # ------------------------------------------------------------------ #
    def allowed_values(self) -> dict[str, list[str]]:
        a = self.assets
        out = {d: self.groups(d) for d in DIMENSION_COLUMN}
        out["symbol"] = sorted(a.index.tolist())
        return out

    def members(self, dimension: str, target: str) -> pd.Series:
        """Masque booléen (index = symbole) des actifs qui appartiennent au groupe `target` de la dimension."""
        a = self.assets
        t = (target or "").strip().lower()
        if dimension == "symbol":
            return pd.Series(a.index.str.lower() == t, index=a.index)
        col = a[DIMENSION_COLUMN[dimension]].astype(str).str.lower()
        if dimension in SET_DIMENSIONS:
            return col.str.contains(f"{SEP}{t}{SEP}", regex=False)
        return col == t

    def groups(self, dimension: str) -> list[str]:
        """Groupes réels d'une dimension (sans « Non classé », « aucune », « monde »)."""
        col = self.assets[DIMENSION_COLUMN[dimension]].astype(str)
        if dimension in SET_DIMENSIONS:
            values = {v for cell in col for v in cell.split(SEP) if v}
        else:
            values = set(col)
        return sorted(values - NOT_A_GROUP)

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
                    "region": r["region"],
                    "instrument_type": r["instrument_type"],
                    "themes": [x for x in str(r["themes"]).split(SEP) if x],
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
        """Rendements espérés et covariance annualisés (covariance corrigée pour être semi-définie positive)."""
        r = self.returns[symbols]
        hist = (r.mean() * TRADING_DAYS).to_numpy(dtype=float)
        # Le dataset couvre moins d'un an: la moyenne historique est très bruitée. On la rapproche de
        # l'hypothèse de sa classe d'actifs (mêmes hypothèses que le frontend). MU_SHRINK=0 la désactive.
        prior = self.assets.loc[symbols, "asset_class"].map(CLASS_PRIOR_MU).fillna(0.05).to_numpy(dtype=float)
        k = get_settings().mu_shrink
        mu = (1 - k) * hist + k * prior
        cov = r.cov(min_periods=60) * TRADING_DAYS
        var = np.array(np.diag(cov.to_numpy()), dtype=float)
        cov = np.array(cov.fillna(0.0).to_numpy(), dtype=float)  # copie modifiable
        np.fill_diagonal(cov, np.where(np.isnan(var), 0.04, var))
        cov = (cov + cov.T) / 2
        vals, vecs = np.linalg.eigh(cov)
        cov = (vecs * np.clip(vals, 1e-10, None)) @ vecs.T
        return mu, (cov + cov.T) / 2

    def portfolio_metrics(self, weights: dict[str, float]) -> PortfolioMetrics:
        symbols = [s for s, w in weights.items() if w > 0]
        w = np.array([weights[s] for s in symbols], dtype=float)
        w = w / w.sum()
        mu, cov = self.moments(symbols)
        ret = float(mu @ w)
        vol = float(np.sqrt(max(w @ cov @ w, 0.0)))
        rf = get_settings().risk_free_rate
        daily = self.returns[symbols].fillna(0.0).to_numpy() @ w
        curve = np.cumprod(1 + daily)
        drawdown = float((curve / np.maximum.accumulate(curve) - 1).min())
        hhi = float((w**2).sum())
        a = self.assets.loc[symbols]

        def group(col: str) -> dict[str, float]:
            # Les FNB et l'encaisse n'ont ni secteur ni pays: ils ne forment pas un groupe « Non classé ».
            g = pd.Series(w, index=symbols).groupby(a[col].fillna(UNKNOWN)).sum()
            return {k: round(float(v), 4) for k, v in g.sort_values(ascending=False).items() if k not in NOT_A_GROUP}

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
            region_weights=group("region"),
            fees=round(float(self.assets.loc[symbols, "fee"].to_numpy(dtype=float) @ w), 5),
        )


def build_market(df: pd.DataFrame) -> Market:
    """Construit un `Market` à partir du DataFrame long (une ligne par symbole et par date)."""
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Colonnes manquantes dans le dataset: {sorted(missing)}")
    if "is_included_universe" in df.columns:
        df = df[df["is_included_universe"].fillna(False).astype(bool)]

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    returns = df.pivot_table(index="date", columns="symbol", values="total_return_cad", aggfunc="mean").sort_index()
    returns = returns.replace([np.inf, -np.inf], np.nan)
    returns = returns.loc[:, returns.count() >= MIN_OBSERVATIONS]

    meta_cols = [c for c in META_COLUMNS if c in df.columns]
    meta = df.drop_duplicates("symbol").set_index("symbol")[meta_cols]
    for col in META_COLUMNS:
        if col not in meta.columns:
            meta[col] = np.nan
    meta = meta.loc[returns.columns]
    meta["name"] = meta["name"].fillna(pd.Series(meta.index, index=meta.index))
    meta = meta.rename(columns={"asset_class": "asset_class_raw"})

    # Encaisse: absente des données de marché, mais indispensable (classe « liquidités » du frontend).
    rf = get_settings().risk_free_rate
    if CASH_SYMBOL not in returns.columns:
        returns[CASH_SYMBOL] = cash_series(returns.index, rf)
        meta.loc[CASH_SYMBOL, ["name", "instrument_type", "currency"]] = [CASH_NAME, "Cash", "CAD"]

    meta = classify(meta, returns)
    for col in ("sector", "country"):
        meta[col] = meta[col].fillna(UNKNOWN).astype(str)

    ann_ret = returns.mean() * TRADING_DAYS
    ann_vol = returns.std() * np.sqrt(TRADING_DAYS)
    stats = pd.DataFrame(
        {
            "ann_return": ann_ret,
            "ann_vol": ann_vol,
            "sharpe": (ann_ret - rf) / ann_vol.replace(0, np.nan),
            "n_obs": returns.count(),
        }
    ).fillna(0.0)
    assets = meta.join(stats)
    logger.info("Dataset chargé: %d actifs, %d dates", len(assets), len(returns))
    return Market(assets=assets, returns=returns)


@lru_cache(maxsize=1)
def get_market() -> Market:
    path = _resolve_path(get_settings().dataset_path)
    if not Path(path).exists():
        raise FileNotFoundError(
            f"Dataset introuvable: {path}. Exportez le DataFrame de `create_opt_inputs` en Parquet "
            "ou générez un jeu de test avec scripts/make_sample_dataset.py."
        )
    return build_market(pd.read_parquet(path))
