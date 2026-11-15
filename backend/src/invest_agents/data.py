"""Chargement du dataset fixe et calculs de marché (rendements, covariance, métriques)."""

from __future__ import annotations

import difflib
import logging
import re
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .config import get_settings
from .schemas import PortfolioMetrics

logger = logging.getLogger(__name__)

TRADING_DAYS = 252
MIN_OBSERVATIONS = 120
UNKNOWN = "Non classé"

# Colonnes produites par `create_opt_inputs` dans Universe_Cleaned.ipynb
REQUIRED_COLUMNS = {"date", "symbol", "total_return_cad"}
META_COLUMNS = ["name", "sector", "industry", "country", "currency", "asset_class", "instrument_type", "market"]

# Rendement espéré: la moyenne 2021-2026 reflète un marché haussier et les gagnants de la période (biais du
# survivant). On la ramène vers un rendement de long terme par classe d'actifs, en CAD, sans en garder les extrêmes.
CLASS_RETURNS = {"Equity": 0.07, "Fixed Income": 0.035, "Real Estate": 0.06, "Multi-Asset": 0.055,
                 "Commodities": 0.045, "Alternative": 0.06}
DEFAULT_RETURN = 0.05
HISTORY_WEIGHT = 0.25  # part de l'historique dans le rendement espéré
HISTORY_CLIP = (-0.10, 0.30)


def _resolve_path(path: str) -> str:
    """Télécharge le fichier si c'est une URI S3, sinon retourne le chemin local.

    Le cache local (/tmp) est nommé d'après la version de l'objet (VersionId, sinon ETag): remplacer l'objet
    dans S3 force un nouveau téléchargement au prochain démarrage à froid.
    """
    if not path.startswith("s3://"):
        return path
    import boto3

    bucket, _, key = path[len("s3://") :].partition("/")
    s3 = boto3.client("s3", region_name=get_settings().region)
    head = s3.head_object(Bucket=bucket, Key=key)
    version_id = head.get("VersionId")
    if version_id == "null":  # objet déposé avant l'activation du versioning
        version_id = None
    tag = re.sub(r"[^A-Za-z0-9._-]", "_", version_id or head["ETag"].strip('"'))
    target = Path(tempfile.gettempdir()) / f"dataset-{tag}-{Path(key).name}"
    if not target.exists():
        logger.info("Téléchargement du dataset depuis %s (version %s)", path, tag)
        partial = target.with_name(target.name + ".part")
        s3.download_file(bucket, key, str(partial), ExtraArgs={"VersionId": version_id} if version_id else None)
        partial.replace(target)  # atomique: un téléchargement interrompu ne laisse pas de fichier tronqué
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
        return {
            "sector": sorted(a["sector"].dropna().unique().tolist()),
            "country": sorted(a["country"].dropna().unique().tolist()),
            "asset_class": sorted(a["asset_class"].dropna().unique().tolist()),
            "symbol": sorted(a.index.tolist()),
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
        """Rendements espérés et covariance annualisés (covariance corrigée pour être semi-définie positive)."""
        r = self.returns[symbols]
        mu = self.assets.loc[symbols, "ann_return"].to_numpy(dtype=float)
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
    # get_market lit les métadonnées en catégories (mémoire); une ligne par symbole suffit pour revenir au texte.
    meta = meta.astype({c: meta[c].cat.categories.dtype for c in meta_cols
                        if isinstance(meta[c].dtype, pd.CategoricalDtype)})
    for col in META_COLUMNS:
        if col not in meta.columns:
            meta[col] = np.nan
    meta = meta.loc[returns.columns]
    meta["name"] = meta["name"].fillna(pd.Series(meta.index, index=meta.index))
    for col in ("sector", "country", "asset_class"):
        meta[col] = meta[col].fillna(UNKNOWN).astype(str)

    rf = get_settings().risk_free_rate
    hist_ret = returns.mean() * TRADING_DAYS
    prior = meta["asset_class"].map(CLASS_RETURNS).fillna(DEFAULT_RETURN)
    ann_ret = (1 - HISTORY_WEIGHT) * prior + HISTORY_WEIGHT * hist_ret.clip(*HISTORY_CLIP)
    ann_vol = returns.std() * np.sqrt(TRADING_DAYS)
    stats = pd.DataFrame(
        {
            "hist_return": hist_ret,
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
    return build_market(_read_dataset(path))


def _read_dataset(path: str) -> pd.DataFrame:
    """Lit seulement les colonnes utiles. Les métadonnées texte, répétées sur chaque date, sont lues en
    dictionnaire (catégories): sur le dataset réel (1,2 M lignes), le pic mémoire passe d'environ 850 Mo à
    environ 440 Mo, ce qui compte sur la petite EC2 du front (t3.small, 2 Go)."""
    import pyarrow.parquet as pq

    schema = pq.read_schema(path)
    wanted = REQUIRED_COLUMNS | set(META_COLUMNS) | {"is_included_universe"}
    columns = [name for name in schema.names if name in wanted]
    text = [name for name in columns
            if name in META_COLUMNS and str(schema.field(name).type) in ("string", "large_string")]
    table = pq.read_table(path, columns=columns, read_dictionary=text)
    return table.to_pandas(self_destruct=True, split_blocks=True)  # libère les tampons Arrow au fil de la conversion
