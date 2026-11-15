"""Contexte macro US et Canada: table longue `macro_long_z` (taux, écart 10 ans-2 ans, taux directeur, inflation, chômage).

Code pur, sans LLM: les outils de `tools.make_macro_tools` l'exposent aux gestionnaires, aux agents Risque et au juge.
Source: `MONPORT_MACRO_PARQUET_URI` (local ou s3://bucket/key), sinon `data/macro_long_z.parquet`. Le fichier est lu
au premier appel puis gardé en mémoire (environ 95 000 lignes).

Colonnes: date, country, metric, metric_value (en %), z_5y (z-score sur 5 ans glissants), z_full (z-score sur tout
l'historique disponible à la date), history_start_date, ref_period (période décrite par la valeur: l'inflation et le
chômage sont publiés avec retard).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from .data import load_market_data

logger = logging.getLogger(__name__)

MACRO_ENV_VAR = "MONPORT_MACRO_PARQUET_URI"
DEFAULT_MACRO_PATH = Path(__file__).resolve().parents[2] / "data" / "macro_long_z.parquet"

COUNTRIES = ("US", "CA")
METRICS = ("yield_10y", "yield_2y", "spread_10y_2y", "policy_rate", "inflation_yoy", "unemployment_rate")
FREQUENCIES = ("monthly", "native")
REQUIRED_COLUMNS = ("date", "country", "metric", "metric_value", "z_5y", "z_full", "history_start_date", "ref_period")
DATE_COLUMNS = ("date", "history_start_date", "ref_period")
MAX_ROWS = 1000


@dataclass(frozen=True)
class MacroData:
    frame: pd.DataFrame  # trié par country, metric, date
    last_date: pd.Timestamp  # date la plus récente du fichier
    source: str


def get_macro_source() -> str:
    return os.getenv(MACRO_ENV_VAR, "").strip() or str(DEFAULT_MACRO_PATH)


def prepare_macro(frame: pd.DataFrame, source: str = "") -> MacroData:
    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"Table macro incomplète, colonnes absentes: {missing}")
    df = frame.loc[:, list(REQUIRED_COLUMNS)].copy()
    for col in DATE_COLUMNS:
        df[col] = pd.to_datetime(df[col])
    df["country"] = df["country"].astype(str).str.upper()
    df["metric"] = df["metric"].astype(str)
    df = df.dropna(subset=["date", "metric_value"]).sort_values(["country", "metric", "date"]).reset_index(drop=True)
    if df.empty:
        raise ValueError("Table macro vide.")
    return MacroData(frame=df, last_date=df["date"].max(), source=source)


_lock = threading.Lock()
_cache: Optional[MacroData] = None


def get_macro() -> MacroData:
    """Charge la table une seule fois (les outils de plusieurs agents l'appellent en parallèle)."""
    global _cache
    with _lock:
        if _cache is None:
            source = get_macro_source()
            if not source.startswith("s3://") and not Path(source).is_file():
                raise FileNotFoundError(f"Table macro introuvable: {source}. Définir {MACRO_ENV_VAR}.")
            _cache = prepare_macro(load_market_data(source), source)
            logger.info("Table macro chargée: %d lignes, jusqu'au %s (%s)", len(_cache.frame),
                        _cache.last_date.date(), source)
        return _cache


def _records(df: pd.DataFrame) -> list[dict]:
    out = df.copy()
    for col in DATE_COLUMNS:
        out[col] = out[col].dt.strftime("%Y-%m-%d")
    for col in ("metric_value", "z_5y", "z_full"):
        out[col] = out[col].round(4)
    return json.loads(out.to_json(orient="records"))  # NaN -> null


def _date(value: str, name: str) -> Optional[pd.Timestamp]:
    if not value:
        return None
    try:
        return pd.Timestamp(value)
    except ValueError as exc:
        raise ValueError(f"{name} invalide: {value!r} (format attendu AAAA-MM-JJ).") from exc


def latest_snapshot(macro: MacroData) -> dict:
    """Dernière ligne de chaque (pays, indicateur), avec `days_stale` = jours entre cette ligne et la date la plus récente."""
    latest = macro.frame.groupby(["country", "metric"], as_index=False).tail(1).copy()
    latest["days_stale"] = (macro.last_date - latest["date"]).dt.days
    return {"as_of_file_date": macro.last_date.strftime("%Y-%m-%d"), "units": "metric_value en %",
            "rows": _records(latest.sort_values(["country", "metric"]))}


def history(
    macro: MacroData,
    country: str = "",
    metric: str = "",
    start_date: str = "",
    end_date: str = "",
    frequency: str = "monthly",
    max_rows: int = 600,
) -> dict:
    """Historique filtré. `monthly` garde la dernière observation de chaque mois; au-delà de `max_rows`, les plus récentes."""
    country = country.strip().upper()
    metric = metric.strip().lower()
    if country and country not in COUNTRIES:
        raise ValueError(f"Pays inconnu: {country!r}. Valeurs possibles: {', '.join(COUNTRIES)}.")
    if metric and metric not in METRICS:
        raise ValueError(f"Indicateur inconnu: {metric!r}. Valeurs possibles: {', '.join(METRICS)}.")
    if frequency not in FREQUENCIES:
        raise ValueError(f"Fréquence inconnue: {frequency!r}. Valeurs possibles: {', '.join(FREQUENCIES)}.")
    start, end = _date(start_date, "start_date"), _date(end_date, "end_date")
    limit = max(1, min(int(max_rows), MAX_ROWS))

    df = macro.frame
    if country:
        df = df[df["country"] == country]
    if metric:
        df = df[df["metric"] == metric]
    if start is not None:
        df = df[df["date"] >= start]
    if end is not None:
        df = df[df["date"] <= end]
    if frequency == "monthly":
        month = df["date"].dt.to_period("M")
        df = df.groupby([df["country"], df["metric"], month], sort=False).tail(1)
    df = df.sort_values(["date", "country", "metric"])

    total = len(df)
    truncated = total > limit
    if truncated:
        df = df.tail(limit)
    return {"total_rows": total, "returned_rows": len(df), "truncated": truncated, "units": "metric_value en %",
            "rows": _records(df)}
