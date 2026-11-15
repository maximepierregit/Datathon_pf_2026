

from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ADAPTER ICI AVEC KIRO : source locale de développement ou URI S3.
# Exemple : "s3://mon-bucket/mon-prefix/universe.parquet"
# La variable d'environnement a priorité sur cette valeur.
# ---------------------------------------------------------------------------
DEFAULT_PARQUET_PATH = "data/universe.parquet"
PARQUET_SOURCE = os.getenv("MONPORT_UNIVERSE_PARQUET_URI", DEFAULT_PARQUET_PATH)

RETURN_COLUMN = "total_return_cad"
PRICE_COLUMN = "close_price_cad"
FORWARD_RETURN_COLUMN = "total_return_cad_fwd_1d"

REQUIRED_COLUMNS = (
    "date", "symbol", RETURN_COLUMN, PRICE_COLUMN,
    "asset_class", "instrument_type", "is_included_universe",
)
OPTIONAL_METADATA_COLUMNS = (
    "name", "currency", "sector", "industry", "country", "market",
    "market_cap", "category_group", "category", "theme",
)
NUMERIC_COLUMNS = (
    RETURN_COLUMN, FORWARD_RETURN_COLUMN,
    "close_price_loc", "fx_rate_to_cad", PRICE_COLUMN,
)
VALID_ASSET_CLASSES = frozenset({
    "Equity", "Fixed Income", "Multi-Asset", "Real Estate",
    "Commodities", "Alternative",
})
VALID_INSTRUMENT_TYPES = frozenset({"Stock", "ETF", "Cryptocurrency"})
UNKNOWN_LABELS = frozenset({"", "non classé", "non classe", "unknown", "n/a"})

# Les régions sont déterminées seulement quand la domiciliation est connue.
# Les ETF n'ont PAS de look-through géographique dans ce Parquet.
STOCK_COUNTRY_TO_REGION = {
    "Canada": "canada",
    "United States": "usa",
    "France": "europe",
    "Germany": "europe",
    "United Kingdom": "europe",
    "Ireland": "europe",
    "Netherlands": "europe",
    "Switzerland": "europe",
    "Luxembourg": "europe",
    "Singapore": "asie",
    "Australia": "asie",
}


@dataclass
class OptimizerData:
    """Ensemble cohérent d'entrées, sans estimation de mu/Sigma."""

    panel: pd.DataFrame
    universe: pd.DataFrame
    eligible_universe: pd.DataFrame
    stock_universe: pd.DataFrame
    etf_universe: pd.DataFrame
    crypto_universe: pd.DataFrame
    theme_membership: pd.DataFrame
    returns: pd.DataFrame
    prices: pd.DataFrame
    benchmark_returns: pd.DataFrame
    history_counts: pd.Series
    excluded_short_history: list[str]
    validation_report: pd.DataFrame
    as_of: pd.Timestamp


def _as_date(value: str | pd.Timestamp | None) -> pd.Timestamp | None:
    """Normaliser une borne de date (incluse), ou laisser None."""
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="raise")
    if isinstance(parsed, pd.DatetimeIndex):
        raise TypeError("Une seule date est attendue.")
    if pd.isna(parsed):
        raise ValueError("La date ne peut pas être NaT.")
    return pd.Timestamp(parsed).tz_localize(None).normalize() if parsed.tzinfo else pd.Timestamp(parsed).normalize()


def _unique_symbols(symbols: Sequence[str] | None) -> list[str] | None:
    """Normaliser les tickers en conservant leur ordre, sans les coder en dur."""
    if symbols is None:
        return None
    if isinstance(symbols, str):
        raise TypeError("symbols doit être une séquence de tickers, pas une chaîne.")
    clean = [str(s).strip().upper() for s in symbols]
    if not clean or any(not s for s in clean):
        raise ValueError("La liste de symboles est vide ou contient une valeur vide.")
    return list(dict.fromkeys(clean))


def _parse_bool(value: Any) -> Any:
    """Interpréter explicitement les valeurs d'admissibilité."""
    if value is None or value is pd.NA:
        return pd.NA
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "oui", "y"}:
            return True
        if text in {"false", "0", "no", "non", "n"}:
            return False
    return pd.NA


def load_market_data(
    path: str | Path | None = None,
    *,
    columns: Sequence[str] | None = None,
    s3_client: Any | None = None,
) -> pd.DataFrame:
    """Lire un Parquet local ou S3 via boto3 ; ne pas inventer d'autres données.

    S3 : les credentials sont résolus par AWS (IAM role, profil ou variables
    d'environnement). Aucun s3fs n'est nécessaire ; pyarrow reste requis.
    """
    source = str(path or PARQUET_SOURCE)
    requested_columns = list(columns) if columns is not None else None

    if source.startswith("s3://"):
        parsed = urlparse(source)
        bucket, key = parsed.netloc, parsed.path.lstrip("/")
        if not bucket or not key:
            raise ValueError(f"URI S3 incomplète : {source!r}")
        if s3_client is None:
            try:
                import boto3
            except ImportError as exc:
                raise ImportError("Installer boto3 pour charger un Parquet S3.") from exc
            s3_client = boto3.client("s3")
        logger.info("Lecture du Parquet sur S3 : s3://%s/%s", bucket, key)
        response = s3_client.get_object(Bucket=bucket, Key=key)
        with BytesIO(response["Body"].read()) as buffer:
            frame = pd.read_parquet(buffer, columns=requested_columns)
    else:
        local_path = Path(source).expanduser()
        if not local_path.is_file():
            raise FileNotFoundError(
                f"Parquet introuvable : {local_path}. "
                "Modifier DEFAULT_PARQUET_PATH ou MONPORT_UNIVERSE_PARQUET_URI."
            )
        logger.info("Lecture du Parquet local : %s", local_path)
        frame = pd.read_parquet(local_path, columns=requested_columns)

    if frame.empty:
        raise ValueError("Le Parquet est vide.")
    return frame


def normalize_market_data(frame: pd.DataFrame) -> pd.DataFrame:
    """Standardiser types, dates et tickers sans modifier les rendements."""
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame doit être un DataFrame pandas.")
    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"Colonnes obligatoires absentes : {missing}")

    df = frame.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if isinstance(df["date"].dtype, pd.DatetimeTZDtype):
        df["date"] = df["date"].dt.tz_localize(None)
    df["date"] = df["date"].dt.normalize()
    df["symbol"] = df["symbol"].astype("string").str.strip().str.upper()

    for column in NUMERIC_COLUMNS:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    for column in ("asset_class", "instrument_type", *OPTIONAL_METADATA_COLUMNS):
        if column in df.columns:
            df[column] = df[column].astype("string").str.strip()

    df["is_included_universe"] = (
        df["is_included_universe"].map(_parse_bool).astype("boolean")
    )
    return df.sort_values(["date", "symbol"], kind="stable").reset_index(drop=True)


def validate_market_data(
    frame: pd.DataFrame,
    *,
    strict: bool = True,
    price_fx_rtol: float = 1e-6,
    check_metadata: bool = True,
) -> pd.DataFrame:
    """Contrôler l'intégrité sans supprimer des jours ni des valeurs extrêmes.

    Les absences à la construction de la matrice (IPO/jours fériés) sont
    structurelles : elles NE sont PAS des erreurs dans ce panel longitudinal.
    """
    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"Colonnes obligatoires absentes : {missing}")
    issues: list[dict[str, Any]] = []

    def report(severity: str, code: str, mask: pd.Series, detail: str) -> None:
        count = int(mask.fillna(False).sum())
        if count:
            issues.append({"severity": severity, "code": code,
                           "count": count, "detail": detail})

    report("ERROR", "invalid_dates", frame["date"].isna(), "Dates manquantes/invalides")
    report("ERROR", "invalid_symbols",
           frame["symbol"].isna() | frame["symbol"].eq(""), "Symboles invalides")
    report("ERROR", "duplicate_date_symbol",
           frame.duplicated(["date", "symbol"], keep=False), "Doublons date/symbole")
    report("ERROR", "invalid_inclusion_flag",
           frame["is_included_universe"].isna(), "Drapeau d'admissibilité invalide")
    report("ERROR", "invalid_asset_class",
           ~frame["asset_class"].isin(VALID_ASSET_CLASSES), "Classe d'actifs non reconnue")
    report("ERROR", "invalid_instrument_type",
           ~frame["instrument_type"].isin(VALID_INSTRUMENT_TYPES), "Type d'instrument inconnu")

    ret = frame[RETURN_COLUMN].to_numpy(dtype=float, na_value=np.nan)
    report("ERROR", "invalid_returns",
           pd.Series(~np.isfinite(ret), index=frame.index), "Rendements manquants/inf")
    report("ERROR", "returns_below_minus_100pct",
           pd.Series(ret < -1, index=frame.index), "Rendement simple inférieur à -100 %")

    for column in ("close_price_loc", "fx_rate_to_cad", PRICE_COLUMN):
        if column in frame.columns:
            values = frame[column].to_numpy(dtype=float, na_value=np.nan)
            report("ERROR", f"invalid_{column}",
                   pd.Series((~np.isfinite(values)) | (values <= 0), index=frame.index),
                   f"{column} doit être strictement positif et fini")

    if {"currency", "fx_rate_to_cad"}.issubset(frame.columns):
        cad = frame["currency"].eq("CAD").fillna(False).to_numpy(dtype=bool)
        fx = frame["fx_rate_to_cad"].to_numpy(dtype=float, na_value=np.nan)
        report("ERROR", "cad_fx_not_one",
               pd.Series(cad & np.isfinite(fx) & (~np.isclose(fx, 1.0, atol=1e-9)), index=frame.index),
               "Le FX d'un titre en CAD doit être égal à 1")

    if {"close_price_loc", "fx_rate_to_cad", PRICE_COLUMN}.issubset(frame.columns):
        expected = frame["close_price_loc"].to_numpy(dtype=float, na_value=np.nan) * frame["fx_rate_to_cad"].to_numpy(dtype=float, na_value=np.nan)
        recorded = frame[PRICE_COLUMN].to_numpy(dtype=float, na_value=np.nan)
        report("ERROR", "price_fx_inconsistency",
               pd.Series(np.isfinite(expected) & np.isfinite(recorded) &
                         ~np.isclose(expected, recorded, rtol=price_fx_rtol, atol=1e-8), index=frame.index),
               "Prix CAD différent de prix local × FX")

    # Vérification facultative de la cohérence rendement/prix : le premier
    # rendement d'un symbole peut venir du burn-in antérieur au Parquet.
    if PRICE_COLUMN in frame.columns and not frame[["date", "symbol"]].isna().any().any():
        ordered = frame.sort_values(["symbol", "date"], kind="stable")
        previous = ordered.groupby("symbol", sort=False)[PRICE_COLUMN].shift(1)
        calculated = ordered[PRICE_COLUMN].div(previous).sub(1)
        reported = ordered[RETURN_COLUMN]
        valid = previous.notna() & calculated.notna() & reported.notna()
        mismatch = valid & ~np.isclose(calculated, reported, rtol=1e-5, atol=1e-7)
        report("WARNING", "return_price_inconsistency", mismatch,
               "Rendement différent du ratio des prix CAD ajustés")

    if check_metadata:
        for column in ("asset_class", "instrument_type", "currency", "sector", "country", "theme"):
            if column in frame.columns:
                variations = frame.groupby("symbol", dropna=False)[column].nunique(dropna=False)
                bad_symbols = variations[variations > 1].index
                if len(bad_symbols):
                    report("WARNING", f"changing_{column}", frame["symbol"].isin(bad_symbols),
                           f"Métadonnées {column} variables selon la date")

    result = pd.DataFrame(issues, columns=["severity", "code", "count", "detail"])
    if strict and not result.empty and (result["severity"] == "ERROR").any():
        errors = result.loc[result["severity"] == "ERROR", ["code", "count"]]
        raise ValueError("Validation des données échouée : " + errors.to_dict("records").__str__())
    return result


def filter_market_data(
    frame: pd.DataFrame,
    *,
    as_of: str | pd.Timestamp | None = None,
    start_date: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Appliquer uniquement des bornes temporelles, sans look-ahead."""
    last = _as_date(as_of)
    first = _as_date(start_date)
    if first is not None and last is not None and first > last:
        raise ValueError("start_date ne peut pas dépasser as_of.")
    result = frame
    if first is not None:
        result = result.loc[result["date"] >= first]
    if last is not None:
        result = result.loc[result["date"] <= last]
    if result.empty:
        raise ValueError("Aucune observation sur la période demandée.")
    return result.copy()


def build_universe(
    frame: pd.DataFrame,
    *,
    as_of: str | pd.Timestamp | None = None,
    region_overrides: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Produire une ligne par symbole ; préserver les 6 asset_class sources.

    Les ETF ont country/sector = 'Non classé' dans la source : ne PAS inventer
    un secteur, une région ou une exposition économique par simple ticker.
    region_overrides peut être fourni ultérieurement via config.py, à partir
    d'une table d'expositions vérifiée.
    """
    data = filter_market_data(frame, as_of=as_of)
    counts = data.groupby("symbol", sort=False)[RETURN_COLUMN].count().rename("observations")
    first = data.groupby("symbol", sort=False)["date"].min().rename("first_date")
    last = data.groupby("symbol", sort=False)["date"].max().rename("last_date")
    latest = (data.sort_values(["date", "symbol"], kind="stable")
              .drop_duplicates("symbol", keep="last")
              .set_index("symbol", drop=True))

    desired = ["name", "asset_class", "instrument_type", "currency", "sector", "industry",
               "country", "market", "market_cap", "category_group", "category", "theme",
               "is_included_universe"]
    meta = latest.reindex(columns=desired).join([counts, first, last])
    meta.index.name = "symbol"

    # Une région de domiciliation est attribuée uniquement aux actions.
    meta["region"] = pd.Series(pd.NA, index=meta.index, dtype="string")
    stocks = meta["instrument_type"].eq("Stock").fillna(False)
    meta.loc[stocks, "region"] = meta.loc[stocks, "country"].map(STOCK_COUNTRY_TO_REGION).astype("string")
    if region_overrides:
        for symbol, region in region_overrides.items():
            ticker = str(symbol).strip().upper()
            if ticker in meta.index:
                meta.loc[ticker, "region"] = str(region).strip().lower()

    return meta.sort_index()


def build_theme_membership(universe: pd.DataFrame) -> pd.DataFrame:
    """Déplier 'ia;tech' en associations (symbol, theme) distinctes."""
    if "theme" not in universe.columns:
        return pd.DataFrame(columns=["symbol", "theme"])
    tags = (
        universe["theme"].dropna().astype(str)
        .str.split(";").explode().str.strip().str.lower()
    )
    tags = tags.loc[tags.ne("") & ~tags.isin(UNKNOWN_LABELS)]
    result = tags.rename("theme").reset_index()
    return result.drop_duplicates(["symbol", "theme"]).sort_values(["symbol", "theme"]).reset_index(drop=True)


def build_instrument_views(universe: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Trois vues de métadonnées ; ne pas séparer les rendements pour Sigma."""
    kind = universe["instrument_type"]
    return {
        "stocks": universe.loc[kind.eq("Stock").fillna(False)].copy(),
        "etfs": universe.loc[kind.eq("ETF").fillna(False)].copy(),
        "crypto": universe.loc[kind.eq("Cryptocurrency").fillna(False)].copy(),
    }


def _pivot_values(frame: pd.DataFrame, symbols: Sequence[str], value_column: str) -> pd.DataFrame:
    """Pivot date × ticker ; NaN structurels conservés (IPO, jours fériés)."""
    wanted = _unique_symbols(symbols)
    if wanted is None:
        raise ValueError("Une liste de symboles est nécessaire pour la matrice.")
    if value_column not in frame.columns:
        raise ValueError(f"Colonne absente : {value_column}")
    subset = frame.loc[frame["symbol"].isin(wanted), ["date", "symbol", value_column]]
    if subset.empty:
        raise ValueError("Aucune observation pour les symboles sélectionnés.")
    matrix = subset.pivot(index="date", columns="symbol", values=value_column)
    matrix = matrix.sort_index().reindex(columns=wanted)
    matrix.columns.name = None
    matrix.index.name = "date"
    return matrix


def build_returns_matrix(frame: pd.DataFrame, symbols: Sequence[str]) -> pd.DataFrame:
    """Rendements simples en CAD : jamais de forward-fill ou de zero-fill."""
    return _pivot_values(frame, symbols, RETURN_COLUMN)


def build_price_matrix(frame: pd.DataFrame, symbols: Sequence[str]) -> pd.DataFrame:
    """Prix ajustés en CAD, pour contrôle/visualisation (pas recalcul de mu)."""
    return _pivot_values(frame, symbols, PRICE_COLUMN)


def describe_market_data(frame: pd.DataFrame) -> dict[str, Any]:
    """Résumé descriptif utile pour contrôler une nouvelle extraction."""
    dates = frame["date"].dropna()
    counts = frame.groupby("instrument_type", dropna=False)["symbol"].nunique()
    return {
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "symbols": int(frame["symbol"].nunique()),
        "first_date": str(dates.min().date()) if not dates.empty else None,
        "last_date": str(dates.max().date()) if not dates.empty else None,
        "weekend_rows": int(frame["date"].dt.dayofweek.ge(5).sum()),
        "symbols_by_instrument_type": counts.to_dict(),
        "asset_classes": sorted(frame["asset_class"].dropna().unique().tolist()),
    }


def prepare_optimizer_data(
    path: str | Path | None = None,
    *,
    symbols: Sequence[str] | None = None,
    benchmark_symbols: Sequence[str] | None = None,
    as_of: str | pd.Timestamp | None = None,
    start_date: str | pd.Timestamp | None = None,
    min_observations: int = 120,
    strict_validation: bool = True,
    region_overrides: Mapping[str, str] | None = None,
    s3_client: Any | None = None,
) -> OptimizerData:
    """Assembler l'input de l'optimiseur, sans estimer rendement ou risque.

    Les benchmarks restent disponibles même si l'utilisateur ne peut pas les
    détenir. Les symboles avec peu de données sont écartés de l'optimisation,
    mais conservés dans panel et universe. 120 = défaut de compatibilité avec
    le backend décrit dans UNIVERSE.md ; config.py pourra le remplacer.
    """
    if not isinstance(min_observations, int) or isinstance(min_observations, bool) or min_observations < 2:
        raise ValueError("min_observations doit être un entier >= 2.")

    raw = load_market_data(path, s3_client=s3_client)
    # Prévenir toute fuite de futur même si une colonne prédictive est présente.
    raw = raw.drop(columns=[FORWARD_RETURN_COLUMN], errors="ignore")
    panel = normalize_market_data(raw)
    validation_report = validate_market_data(panel, strict=strict_validation)

    # Appliquer as_of avant de calculer l'éligibilité et les matrices.
    panel = filter_market_data(panel, as_of=as_of, start_date=start_date)
    last = _as_date(as_of) or panel["date"].max()
    universe = build_universe(panel, region_overrides=region_overrides)
    themes = build_theme_membership(universe)
    views = build_instrument_views(universe)

    eligible_flags = universe["is_included_universe"].fillna(False)
    counts = universe["observations"].astype(int)
    enough_history = counts.ge(min_observations)
    investable = universe.loc[eligible_flags & enough_history]
    excluded_short = sorted(universe.index[eligible_flags & ~enough_history].tolist())

    requested = _unique_symbols(symbols)
    if requested is not None:
        unknown = sorted(set(requested) - set(universe.index))
        if unknown:
            raise ValueError(f"Symboles absents du Parquet : {unknown}")
        not_eligible = [s for s in requested if s not in investable.index]
        if not_eligible:
            raise ValueError(
                "Symboles explicitement demandés mais non admissibles ou avec "
                f"moins de {min_observations} observations : {not_eligible}"
            )
        selected = requested
    else:
        selected = investable.index.tolist()

    if not selected:
        raise ValueError("Aucun actif admissible avec un historique suffisant.")

    returns = build_returns_matrix(panel, selected)
    prices = build_price_matrix(panel, selected)
    # Les deux matrices ont les mêmes dates et le même ordre de colonnes.
    prices = prices.reindex(index=returns.index, columns=returns.columns)

    benchmark_list = _unique_symbols(benchmark_symbols)
    if benchmark_list is None:
        benchmark_returns = pd.DataFrame(index=returns.index)
        benchmark_returns.index.name = "date"
    else:
        missing_benchmark = sorted(set(benchmark_list) - set(universe.index))
        if missing_benchmark:
            raise ValueError(f"Benchmarks absents du Parquet : {missing_benchmark}")
        benchmark_returns = build_returns_matrix(panel, benchmark_list)
        benchmark_returns = benchmark_returns.reindex(index=returns.index)

    logger.info(
        "Préparation : %s actifs investissables, %s retirés (<%s obs), %s dates",
        len(selected), len(excluded_short), min_observations, len(returns),
    )
    return OptimizerData(
        panel=panel,
        universe=universe,
        eligible_universe=investable.reindex(selected),
        stock_universe=views["stocks"],
        etf_universe=views["etfs"],
        crypto_universe=views["crypto"],
        theme_membership=themes,
        returns=returns,
        prices=prices,
        benchmark_returns=benchmark_returns,
        history_counts=counts,
        excluded_short_history=excluded_short,
        validation_report=validation_report,
        as_of=last,
    )


def main() -> None:
    """Exécuter le module seul pour vérifier le chargement local/S3."""
    parser = argparse.ArgumentParser(description="Préparation des données MonPort")
    parser.add_argument("--input", default=None, help="Chemin local ou s3://bucket/key")
    parser.add_argument("--as-of", default=None, help="Date maximale AAAA-MM-JJ")
    parser.add_argument("--start-date", default=None, help="Date minimale AAAA-MM-JJ")
    parser.add_argument("--symbols", nargs="*", default=None, help="Symboles à investir")
    parser.add_argument("--benchmarks", nargs="*", default=None, help="Références de marché")
    parser.add_argument("--min-observations", type=int, default=120)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    result = prepare_optimizer_data(
        path=args.input,
        symbols=args.symbols,
        benchmark_symbols=args.benchmarks,
        as_of=args.as_of,
        start_date=args.start_date,
        min_observations=args.min_observations,
    )
    print("\nRÉSUMÉ DU PANEL")
    print(describe_market_data(result.panel))
    print("\nACTIFS RETENUS :", len(result.eligible_universe))
    print("HISTORIQUES TROP COURTS :", result.excluded_short_history)
    print("MATRICE DES RENDEMENTS :", result.returns.shape)
    print("VALEURS MANQUANTES STRUCTURELLES :", int(result.returns.isna().sum().sum()))
    print("\nDERNIERS RENDEMENTS CAD :")
    preview = result.returns.columns[:10]
    print(result.returns.loc[:, preview].tail(3).to_string())
    if len(result.returns.columns) > len(preview):
        print(f"... aperçu de {len(preview)} actifs sur {len(result.returns.columns)}")


if __name__ == "__main__":
    main()
