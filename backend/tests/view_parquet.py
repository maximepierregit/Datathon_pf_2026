"""Visualiser le Parquet de l'univers (aperçu, schéma, valeurs uniques) sans le charger en entier.

Par défaut lit config.get_parquet_source() (chemin local ou s3://). Lecture seule.

Exemples (depuis backend/) :
    python tests/view_parquet.py                          # résumé + valeurs uniques + aperçu
    python tests/view_parquet.py --values sector country  # valeurs uniques d'autres colonnes
    python tests/view_parquet.py --symbol AAPL            # dernières lignes d'un symbole
    python tests/view_parquet.py --symbols --limit 50     # une ligne de métadonnées par symbole
    python tests/view_parquet.py --path data/universe.parquet --head 20
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from invest_agents import config  # noqa: E402

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 50)
pd.set_option("display.max_colwidth", 40)
pd.set_option("display.max_rows", 500)

META_COLUMNS = [
    "symbol", "name", "instrument_type", "asset_class", "sector", "industry",
    "country", "currency", "market", "category_group", "category", "theme",
    "market_cap", "is_included_universe",
]


def title(text: str) -> None:
    print(f"\n{'=' * 78}\n{text}\n{'=' * 78}")


def open_source(path: str):
    """Fichier Parquet local ou objet S3 (téléchargé en mémoire) -> ParquetFile."""
    if path.startswith("s3://"):
        from io import BytesIO
        from urllib.parse import urlparse

        import boto3

        parsed = urlparse(path)
        body = boto3.client("s3").get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))["Body"].read()
        return pq.ParquetFile(BytesIO(body)), BytesIO(body)
    if not Path(path).is_file():
        sys.exit(f"Parquet introuvable : {path}")
    return pq.ParquetFile(path), path


def read(source, columns=None, filters=None) -> pd.DataFrame:
    if hasattr(source, "seek"):
        source.seek(0)
    return pd.read_parquet(source, columns=columns, filters=filters)


def symbol_level(source, available: list[str]) -> pd.DataFrame:
    """Une ligne par symbole (dernière date), colonnes de métadonnées seulement."""
    wanted = [c for c in dict.fromkeys(["date", *META_COLUMNS]) if c in available]
    frame = read(source, columns=wanted)
    if "date" in frame.columns:
        frame = frame.sort_values("date", kind="stable")
    return frame.drop_duplicates("symbol", keep="last").drop(columns="date", errors="ignore").set_index("symbol").sort_index()


def show_unique(per_symbol: pd.DataFrame, column: str) -> None:
    """Valeurs uniques d'une colonne, comptées en nombre de symboles (NaN inclus)."""
    if column not in per_symbol.columns:
        print(f"\n[{column}] colonne absente.")
        return
    counts = per_symbol[column].value_counts(dropna=False)
    print(f"\n{column} : {len(counts)} valeurs uniques (nombre de symboles)")
    print(counts.rename_axis(column).to_frame("symboles").to_string())


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualiser le Parquet de l'univers.")
    parser.add_argument("--path", default=None, help="Chemin local ou s3://... (défaut : config.py)")
    parser.add_argument("--head", type=int, default=10, help="Lignes d'aperçu (défaut 10)")
    parser.add_argument("--values", nargs="*", default=[], help="Colonnes supplémentaires dont afficher les valeurs uniques")
    parser.add_argument("--symbol", default=None, help="Afficher les dernières lignes d'un symbole")
    parser.add_argument("--symbols", action="store_true", help="Table des métadonnées, une ligne par symbole")
    parser.add_argument("--limit", type=int, default=40, help="Lignes max pour --symbols (défaut 40)")
    args = parser.parse_args()

    path = args.path or config.get_parquet_source()
    parquet, source = open_source(path)
    schema = parquet.schema_arrow
    available = list(schema.names)

    title(f"FICHIER : {path}")
    print(f"Lignes : {parquet.metadata.num_rows:,}   Colonnes : {len(available)}   Row groups : {parquet.num_row_groups}")
    if isinstance(source, (str, Path)):
        print(f"Taille : {Path(source).stat().st_size / 1e6:.1f} Mo")

    title("SCHÉMA")
    print(pd.DataFrame({"colonne": available, "type": [str(t) for t in schema.types]}).to_string(index=False))

    if args.symbol:
        title(f"SYMBOLE : {args.symbol.upper()}")
        rows = read(source, filters=[("symbol", "==", args.symbol.upper())])
        if rows.empty:
            sys.exit(f"Symbole absent : {args.symbol}")
        print(f"{len(rows):,} lignes, du {rows['date'].min():%Y-%m-%d} au {rows['date'].max():%Y-%m-%d}")
        print(rows.sort_values("date").tail(args.head).to_string(index=False))
        return

    per_symbol = symbol_level(source, available)

    title("RÉSUMÉ")
    dates = read(source, columns=["date"])["date"]
    print(f"Symboles : {len(per_symbol):,}   Dates : du {dates.min():%Y-%m-%d} au {dates.max():%Y-%m-%d} ({dates.nunique():,} jours)")
    if "is_included_universe" in per_symbol.columns:
        print("is_included_universe (symboles) :", per_symbol["is_included_universe"].value_counts(dropna=False).to_dict())

    title("VALEURS UNIQUES : asset_class et instrument_type")
    show_unique(per_symbol, "asset_class")
    show_unique(per_symbol, "instrument_type")
    if {"asset_class", "instrument_type"} <= set(per_symbol.columns):
        print("\nasset_class x instrument_type (nombre de symboles)")
        print(pd.crosstab(per_symbol["asset_class"].fillna("<NA>"), per_symbol["instrument_type"].fillna("<NA>"), margins=True).to_string())

    for column in args.values:
        show_unique(per_symbol, column)

    if args.symbols:
        title(f"MÉTADONNÉES PAR SYMBOLE (premiers {args.limit})")
        print(per_symbol.head(args.limit).to_string())

    title(f"APERÇU : {args.head} premières lignes")
    head = next(parquet.iter_batches(batch_size=args.head)).to_pandas()
    print(head.to_string(index=False))


if __name__ == "__main__":
    main()

