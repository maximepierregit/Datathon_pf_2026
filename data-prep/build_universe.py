"""Construit backend/data/universe.parquet à partir des sources réelles (version script de Universe_Cleaned.ipynb).

Étapes (chaque couche « raw » est mise en cache dans backend/data/raw/ et réutilisée si elle existe):

1. catalog  : tickers S&P 500 / TSX / CAC 40 (Wikipedia) + FNB + cryptos, métadonnées financedatabase,
              corrections manuelles des FNB (BITW, NICO), filtre de capitalisation (Mid/Large/Mega).
              -> raw/catalog.parquet (une ligne par symbole)
2. prices   : cours de clôture ajustés yfinance.                    -> raw/prices.parquet
3. fx       : taux USDCAD=X, EURCAD=X, ... (jours civils, ffill).    -> raw/fx.parquet
4. universe : rendements quotidiens en CAD, jointure des thématiques (themes.csv), format long
              (une ligne par date x symbole).                        -> universe.parquet

Usage (depuis la racine du dépôt):

    pip install -r data-prep/requirements.txt
    python data-prep/build_universe.py                 # réutilise le cache raw/ s'il existe
    python data-prep/build_universe.py --refresh all   # tout retélécharger (ou: catalog, prices, fx)
    python data-prep/build_universe.py --upload s3://monport-datasets-381491955506                # construire puis publier
    python data-prep/build_universe.py --upload s3://monport-datasets-381491955506 --upload-only  # publier l'existant
"""

from __future__ import annotations

import argparse
import re
import time
import unicodedata
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "backend" / "data"
RAW = DATA / "raw"
OUT = DATA / "universe.parquet"
THEMES_CSV = Path(__file__).resolve().parent / "themes.csv"

START_DATE = "2021-01-01"  # premier jour des rendements; chaque actif commence quand ses données commencent
END_DATE = "2026-11-10"  # exclusive pour yfinance
# Rodage: prix et taux dès mi-décembre 2020, car le premier rendement exige la clôture précédente.
PRICE_START = str((pd.Timestamp(START_DATE) - pd.Timedelta(days=21)).date())
UNKNOWN = "Non classé"  # sector/industry/country: réservés aux actions (même libellé que le backend)

# --------------------------------------------------------------------------- #
# Univers (repris tel quel du notebook)
# --------------------------------------------------------------------------- #
ETF_TICKERS = [
    # Obligations - CAD gouvernement / société / les deux
    "CLF.TO", "CLG.TO", "VGV.TO", "XRB.TO", "XCB.TO",
    "XBB.TO",   # remplace DACU.TO (lancé 2026-07)
    # Obligations - US gouvernement / société / les deux
    "AGZ", "GOVT", "IEF", "LQD", "HYG", "BND",
    # Mixte (actions et obligations)
    "AOK", "AOM", "AOR", "AOA",
    # Actions - Marchés
    "SPY", "IYY", "IWM", "QQQ", "DIA", "XIU.TO",
    "XIC.TO",   # remplace DACL.TO (lancé 2026-06)
    "VDY.TO", "EWU", "DAX", "EWG", "EWQ", "VGK", "EWJ", "JPXN",
    "EWY",      # couvre aussi KORX.TO (lancé 2026-09, retiré)
    "MCHI", "INDA", "EWZ", "EWW", "ILF", "IPAC", "EFA", "ACWX",
    "XAW.TO",   # remplace DAGL.TO (lancé 2026-07)
    "IOO", "EEM", "EDIV", "BKF",
    # Actions - Thèmes (AIQ couvre aussi AIBF; NICO retiré: tabac exclu, PM/MO restent dans les actions)
    # NSGE.TO retiré: peu transigé, cours inchangé 48 % des jours (ESGU et XESG.TO couvrent l'ESG)
    "XLK", "VGT", "DTCR", "AIQ", "ITA", "SHLD", "ESGU", "XESG.TO",
    "ICLN", "TAN", "AQWA", "BETZ", "MSOS", "BOTZ", "ROBO",
    "XT",       # remplace NTHM.TO (lancé 2026-06)
    # Actions - Secteurs
    "XLF", "XFN.TO", "XLE", "XEG.TO", "XLV", "XLI", "XLY", "XLP", "XLU", "XUT.TO",
    "XLB", "XMA.TO", "XLRE", "XRE.TO", "XLC", "XIT.TO", "SMH", "NREA.TO",
    # Matières premières, crypto (FNB)
    "COMT", "BITW",
]
# financedatabase n'a pas category/category_group/family pour ces FNB (valeurs du notebook).
ETF_METADATA_OVERRIDES = {
    "BITW": {"category": "Digital Assets", "category_group": "Alternative", "family": "Bitwise"},
}
CRYPTO_TICKERS = ["BTC", "ETH"]

# Changements de ticker: l'historique yfinance a migré vers le nouveau symbole (ancien -> nouveau).
SYMBOL_RENAMES = {"TXG.TO": "TXR.TO"}  # Torex Gold -> Torex Resources, 2026-11-03
# Historique inutilisable avant cette date (cours pré-fusion PSA à une autre échelle: +96 % le 2021-01-18).
HISTORY_START = {
    "STLAP.PA": "2021-01-18",
    # Smurfit WestRock cote au NYSE depuis le 2024-07-08 (fusion); avant, yfinance porte une série figée
    # (cours inchangé 33 à 59 % des jours).
    "SW": "2024-07-08",
}
VALID_EQUITY_MKT_CAPS = ["Mid Cap", "Large Cap", "Mega Cap"]

# Libellés de themes.csv -> identifiants de thématique du backend (classify.THEMES).
THEME_IDS = {
    "tech": "tech", "techno": "tech", "technologie": "tech",
    "ai": "ia", "ia": "ia",
    "war": "armement", "war/weaponry": "armement", "armement": "armement",
    "esg": "esg",
    "clean energy": "energie-propre", "energie propre": "energie-propre",
    "vice": "vice",
    "robotics": "robotique", "robotique": "robotique",
    "energie fossile": "fossiles", "fossiles": "fossiles",
}

COLUMNS = ["date", "symbol", "total_return_cad", "total_return_cad_fwd_1d", "close_price_loc", "fx_rate_to_cad", "close_price_cad", "name", "sector", "industry", "country", "currency",
           "asset_class", "instrument_type", "market", "category_group", "category", "market_cap",
           "theme", "is_included_universe"]


# --------------------------------------------------------------------------- #
# 1. Catalogue
# --------------------------------------------------------------------------- #
def get_wiki_table_tickers(url: str, table_id: str | None = None, table_class: str = "wikitable",
                           col_index: int = 0) -> list[str]:
    import requests
    from bs4 import BeautifulSoup

    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    if table_id:
        table = soup.find("table", {"id": table_id})
    else:
        tables = soup.find_all("table", {"class": table_class})
        table = next((t for t in tables if t.find("tr") and any(k in t.find("tr").text.lower()
                                                                 for k in ("ticker", "symbol"))), None)
        table = table or (tables[0] if tables else None)
    if not table:
        raise ValueError(f"Aucune table trouvée à {url}")
    out = []
    for row in table.find_all("tr")[1:]:
        cols = row.find_all(["td", "th"])
        if len(cols) > abs(col_index):
            txt = cols[col_index].text.strip().split("[")[0].strip()
            if txt and txt.lower() not in ("ticker", "symbol", "company"):
                out.append(txt)
    return out


def scrape_equity_tickers() -> list[str]:
    sp500 = [t.replace(".", "-") for t in get_wiki_table_tickers(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", table_id="constituents")]
    cac40 = []
    for t in get_wiki_table_tickers("https://en.wikipedia.org/wiki/CAC_40", col_index=3):
        t = t.split()[0].replace("-", ".")
        cac40.append(t if t.endswith(".PA") else t + ".PA")
    tsx = []
    for t in get_wiki_table_tickers("https://en.wikipedia.org/wiki/S%26P/TSX_Composite_Index"):
        t = t.split()[0].replace(".", "-")
        tsx.append(t if t.endswith(".TO") else t + ".TO")
    return tsx + sp500 + cac40


def _fd_select(db) -> pd.DataFrame:
    """Toutes les places boursières: selon la version, financedatabase ne garde par défaut que les
    bourses américaines (exclude_exchanges=True), ce qui retirerait les titres .TO et .PA."""
    import inspect

    kwargs = {"exclude_exchanges": False} if "exclude_exchanges" in inspect.signature(db.select).parameters else {}
    return db.select(**kwargs).reset_index()


ETF_ASSET_CLASSES = {"Fixed Income": "Fixed Income", "Real Estate": "Real Estate", "Commodities": "Commodities",
                     "Alternative": "Alternative"}


def normalize_asset_class(cat: pd.DataFrame) -> pd.Series:
    """Classe d'actifs brute homogène: Equity, Fixed Income, Multi-Asset, Real Estate, Commodities, Alternative.

    Le notebook reprend le `category_group` des FNB, qui mélange classes d'actifs et secteurs (« Energy »,
    « Information Technology ») et écrit « Equities » au lieu de « Equity ». Le détail reste dans
    `category_group` / `category`."""
    etf = cat["instrument_type"] == "ETF"
    out = cat["asset_class"].copy()
    out[etf] = cat.loc[etf, "category_group"].map(ETF_ASSET_CLASSES).fillna("Equity")
    out[etf & (cat["category"] == "Allocation")] = "Multi-Asset"  # AOK, AOM, AOR, AOA: actions + obligations
    return out


def build_catalog() -> pd.DataFrame:
    """Équivalent de build_base_universe + build_active_universe, en gardant toutes les métadonnées."""
    import financedatabase as fd

    equity_tickers = scrape_equity_tickers()

    eq = _fd_select(fd.Equities())
    eq = eq[eq["symbol"].isin(equity_tickers)].drop_duplicates(subset=["symbol"])
    eq = eq[eq["market_cap"].isin(VALID_EQUITY_MKT_CAPS)]
    eq = eq[["symbol", "name", "currency", "country", "sector", "industry", "market", "market_cap"]].copy()
    eq["instrument_type"], eq["asset_class"] = "Stock", "Equity"

    etf = _fd_select(fd.ETFs())
    etf = etf[(etf["delisted"] == False) & etf["symbol"].isin(ETF_TICKERS)].copy()  # noqa: E712
    for ticker, overrides in ETF_METADATA_OVERRIDES.items():
        for column, value in overrides.items():
            etf.loc[etf["symbol"] == ticker, column] = value
    etf = etf.dropna(subset=["category", "category_group", "family"]).drop_duplicates(subset=["symbol"])
    etf = etf[["symbol", "name", "currency", "category_group", "category", "family"]].copy()
    etf["instrument_type"] = "ETF"
    etf["asset_class"] = etf["category_group"]

    # Filtre sur les colonnes plutôt que via select(): le nom du paramètre change selon la version.
    cr = fd.Cryptos().select().reset_index()
    cr = cr[cr["cryptocurrency"].isin(CRYPTO_TICKERS) & (cr["currency"] == "CAD")]
    cr = cr.drop_duplicates(subset=["symbol"])[["symbol", "name", "currency"]].copy()
    cr["instrument_type"], cr["asset_class"] = "Cryptocurrency", "Alternative"

    print(f"EQUITIES {len(eq)} | ETFs {len(etf)} | CRYPTOS {len(cr)}")
    missing_etfs = sorted(set(ETF_TICKERS) - set(etf["symbol"]))
    if missing_etfs:
        print(f"  ! FNB absents de financedatabase (ignorés): {missing_etfs}")

    cat = pd.concat([eq, etf, cr], ignore_index=True)
    is_stock = cat["instrument_type"] == "Stock"
    for col in ("sector", "industry", "country"):
        cat[col] = cat[col].where(is_stock).fillna(UNKNOWN)
    cat["is_included_universe"] = True
    return cat


# --------------------------------------------------------------------------- #
# 2-3. Prix et taux de change
# --------------------------------------------------------------------------- #
def download_prices(tickers: list[str], chunk_size: int = 50, sleep_sec: float = 1.0) -> pd.DataFrame:
    import yfinance as yf

    warnings.filterwarnings("ignore", category=FutureWarning)
    frames = []
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        raw = yf.download(chunk, PRICE_START, END_DATE, auto_adjust=True, progress=False, threads=True)
        if raw.empty:
            continue
        prices = raw["Close"]
        if isinstance(prices, pd.Series):
            prices = prices.to_frame(name=chunk[0])
        frames.append(prices.reset_index().melt(id_vars="Date", var_name="symbol", value_name="close_price_loc")
                      .dropna(subset=["close_price_loc"]))
        print(f"  prix {min(i + chunk_size, len(tickers))}/{len(tickers)}")
        if sleep_sec and i + chunk_size < len(tickers):
            time.sleep(sleep_sec)
    if not frames:
        return pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"), "symbol": pd.Series(dtype=str),
                             "close_price_loc": pd.Series(dtype=float)})
    df = pd.concat(frames, ignore_index=True).rename(columns={"Date": "date"})
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    return df.sort_values(["symbol", "date"]).reset_index(drop=True)


def download_fx(currencies: list[str]) -> pd.DataFrame:
    """Taux XXX->CAD sur un calendrier civil complet (ffill puis bfill, comme le notebook)."""
    others = sorted(c for c in currencies if c != "CAD")
    px = download_prices([f"{c}CAD=X" for c in others], sleep_sec=0)
    out = []
    for c in others:
        s = px[px["symbol"] == f"{c}CAD=X"].set_index("date")["close_price_loc"]
        if s.empty:
            raise RuntimeError(f"Taux de change {c}CAD introuvable")
        s = s[~s.index.duplicated()].asfreq("D").ffill().bfill()
        out.append(pd.DataFrame({"date": s.index, "currency": c, "fx_rate_to_cad": s.to_numpy()}))
    return pd.concat(out, ignore_index=True)


# --------------------------------------------------------------------------- #
# 4. Rendements et thématiques
# --------------------------------------------------------------------------- #
def _norm_label(label: str) -> str:
    s = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[_\-]+", " ", s).strip()


def load_themes(path: Path) -> pd.Series:
    """ticker -> identifiants de thématique séparés par « ; » (None si aucune)."""
    df = pd.read_csv(path, dtype=str)
    unknown: set[str] = set()

    def convert(cell) -> str | None:
        if not isinstance(cell, str) or not cell.strip():
            return None
        ids = []
        for label in re.split(r"[;|,]", cell):
            if not label.strip():
                continue
            key = _norm_label(label)
            if key not in THEME_IDS:
                unknown.add(label.strip())
                continue
            if THEME_IDS[key] not in ids:
                ids.append(THEME_IDS[key])
        return ";".join(sorted(ids)) or None

    out = df.set_index("ticker")["themes"].map(convert)
    if unknown:
        raise ValueError(f"Thématiques inconnues dans {path.name}: {sorted(unknown)} (compléter THEME_IDS)")
    return out


def compute_returns(prices: pd.DataFrame, catalog: pd.DataFrame, fx: pd.DataFrame) -> pd.DataFrame:
    df = prices.merge(catalog[["symbol", "currency"]], on="symbol", how="inner")
    # Calendrier commun en jours ouvrables: les cryptos cotent 7 j/7. Sans ce filtre, leurs rendements
    # de fin de semaine disparaîtraient de la covariance (absents des autres actifs) et la moyenne
    # quotidienne annualisée sur 252 jours serait faussée. Le rendement du lundi couvre ven -> lun.
    df = df[df["date"].dt.dayofweek < 5]
    df = df.merge(fx, on=["date", "currency"], how="left")
    df.loc[df["currency"] == "CAD", "fx_rate_to_cad"] = 1.0
    missing_fx = df["fx_rate_to_cad"].isna()
    if missing_fx.any():
        raise RuntimeError(f"Taux de change manquant pour {sorted(df.loc[missing_fx, 'currency'].unique())}")
    # Méthode de calculate_returns (notebook), inchangée.
    df = df.sort_values(["symbol", "date"])
    df["close_price_loc"] = df.groupby("symbol")["close_price_loc"].ffill()
    df["close_price_cad"] = df["close_price_loc"] * df["fx_rate_to_cad"]
    df["total_return_cad"] = df.groupby("symbol")["close_price_cad"].pct_change()
    df["total_return_cad_fwd_1d"] = df.groupby("symbol")["total_return_cad"].shift(-1)  # NaN au dernier jour
    # Rodage: les cours avant START_DATE ne servent qu'au premier rendement.
    df = df.dropna(subset=["total_return_cad"])
    df = df[df["date"] >= pd.Timestamp(START_DATE)]
    return df[["date", "symbol", "total_return_cad", "total_return_cad_fwd_1d",
               "close_price_loc", "fx_rate_to_cad", "close_price_cad"]]


def _cached(name: str, refresh: set[str], build) -> pd.DataFrame:
    path = RAW / f"{name}.parquet"
    if path.exists() and name not in refresh and "all" not in refresh:
        print(f"[{name}] cache {path.relative_to(ROOT)}")
        return pd.read_parquet(path)
    print(f"[{name}] construction...")
    df = build()
    RAW.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df


def upload(dest: str, universe: Path) -> None:
    """Publie le dataset dans S3, un dossier par table (lisible tel quel par Athena/Glue au besoin):

    s3://bucket[/prefixe]/universe/universe.parquet   <- lu par le backend (MONPORT_UNIVERSE_PARQUET_URI)
    s3://bucket[/prefixe]/raw/<table>/<table>.parquet <- couches brutes, pour la traçabilité
    """
    import boto3

    if not dest.startswith("s3://"):
        raise SystemExit(f"--upload attend une URI s3://bucket[/prefixe], reçu: {dest}")
    bucket, _, prefix = dest[len("s3://"):].rstrip("/").partition("/")
    prefix = f"{prefix}/" if prefix else ""
    files = {f"{prefix}universe/universe.parquet": universe}
    files |= {f"{prefix}raw/{p.stem}/{p.name}": p for p in sorted(RAW.glob("*.parquet"))}
    s3 = boto3.client("s3")
    for key, path in files.items():
        if not path.exists():
            raise SystemExit(f"Fichier absent: {path}")
        s3.upload_file(str(path), bucket, key, ExtraArgs={"ContentType": "application/vnd.apache.parquet"})
        version = s3.head_object(Bucket=bucket, Key=key).get("VersionId")
        print(f"[upload] {path.name} -> s3://{bucket}/{key} (version {version})")
    print(f"\nMONPORT_UNIVERSE_PARQUET_URI=s3://{bucket}/{prefix}universe/universe.parquet")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", nargs="*", default=[], choices=["all", "catalog", "prices", "fx"])
    ap.add_argument("--themes", type=Path, default=THEMES_CSV)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--no-pin", action="store_true",
                    help="garder les symboles du catalogue absents de themes.csv (sans thématique)")
    ap.add_argument("--upload", metavar="S3_URI",
                    help="publier le résultat dans S3 après la construction, ex. s3://monport-datasets-381491955506")
    ap.add_argument("--upload-only", action="store_true",
                    help="avec --upload: publier les fichiers existants sans reconstruire")
    args = ap.parse_args()
    if args.upload_only:
        if not args.upload:
            ap.error("--upload-only exige --upload")
        upload(args.upload, args.out)
        return
    refresh = set(args.refresh)
    if "catalog" in refresh:
        refresh |= {"prices"}  # un nouveau catalogue peut contenir de nouveaux symboles
    if refresh & {"all", "prices"}:
        (RAW / "prices_missing.parquet").unlink(missing_ok=True)

    catalog = _cached("catalog", refresh, build_catalog).copy()
    catalog["symbol"] = catalog["symbol"].replace(SYMBOL_RENAMES)
    catalog["asset_class"] = normalize_asset_class(catalog)
    prices = _cached("prices", refresh, lambda: download_prices(catalog["symbol"].tolist()))
    # Cache incomplet (nouveaux symboles, renommages): on ne télécharge que ce qui manque.
    tried = set(prices["symbol"]) | set(pd.read_parquet(RAW / "prices_missing.parquet")["symbol"]
                                        if (RAW / "prices_missing.parquet").exists() else [])
    todo = sorted(set(catalog["symbol"]) - tried)
    if todo:
        print(f"[prices] complément: {todo}")
        extra = download_prices(todo)
        prices = pd.concat([prices, extra], ignore_index=True)
        prices.to_parquet(RAW / "prices.parquet", index=False)
        pd.DataFrame({"symbol": sorted(set(todo) - set(extra["symbol"]))}).to_parquet(
            RAW / "prices_missing.parquet", index=False)
    for symbol, start in HISTORY_START.items():
        prices = prices[(prices["symbol"] != symbol) | (prices["date"] >= pd.Timestamp(start))]
    fx = _cached("fx", refresh, lambda: download_fx(catalog["currency"].dropna().unique().tolist()))

    # Thématiques: toutes classes d'actifs confondues.
    themes = load_themes(args.themes).rename(index=SYMBOL_RENAMES)
    not_in_csv = sorted(set(catalog["symbol"]) - set(themes.index))
    not_in_universe = sorted(set(themes.index) - set(catalog["symbol"]))
    # themes.csv fige la liste finale des tickers (804): les indices Wikipedia évoluent (ajouts au TSX, etc.),
    # on ne garde donc que les symboles qui y figurent (sauf --no-pin).
    if not_in_csv:
        action = "conservés sans thématique" if args.no_pin else "retirés"
        print(f"  ! {len(not_in_csv)} symboles absents de {args.themes.name} ({action}): {not_in_csv}")
        if not args.no_pin:
            catalog = catalog[catalog["symbol"].isin(themes.index)]
    if not_in_universe:
        print(f"  ! {len(not_in_universe)} lignes de {args.themes.name} hors univers: {not_in_universe}")
    catalog = catalog.copy()
    catalog["theme"] = catalog["symbol"].map(themes)

    returns = compute_returns(prices, catalog, fx)
    no_prices = sorted(set(catalog["symbol"]) - set(returns["symbol"]))
    if no_prices:
        print(f"  ! {len(no_prices)} symboles sans prix yfinance (retirés): {no_prices}")

    df = returns.merge(catalog, on="symbol", how="inner")
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    df = df[COLUMNS].sort_values(["date", "symbol"]).reset_index(drop=True)
    df["is_included_universe"] = df["is_included_universe"].astype(bool)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.out, index=False)

    # Rapport
    per = df.drop_duplicates("symbol")
    print(f"\n{args.out.relative_to(ROOT)}: {len(df):,} lignes, {per['symbol'].nunique()} symboles, "
          f"{df['date'].min().date()} -> {df['date'].max().date()}")
    print(per["instrument_type"].value_counts().to_string())
    print("Thématiques par type:")
    tags = per.assign(theme=per["theme"].str.split(";")).explode("theme").dropna(subset=["theme"])
    print(pd.crosstab(tags["theme"], tags["instrument_type"]).to_string())
    obs = df.groupby("symbol").size()
    print(f"Observations par symbole: min {obs.min()} ({obs.idxmin()}), médiane {int(obs.median())}")
    big = df[(df["total_return_cad"].abs() > 0.4) & (df["instrument_type"] != "Cryptocurrency")]
    if not big.empty:
        print(f"  ! {len(big)} rendements quotidiens |r| > 40 % (à vérifier):")
        print(big[["date", "symbol", "total_return_cad"]].to_string(index=False))

    if args.upload:
        print()
        upload(args.upload, args.out)


if __name__ == "__main__":
    main()
