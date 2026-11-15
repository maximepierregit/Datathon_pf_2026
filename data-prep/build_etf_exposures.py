"""Construit backend/src/invest_agents/etf_exposures.csv: ce que contient chaque FNB, par secteur et par pays.

Dans universe.parquet, `sector` et `country` sont réservés aux actions (« Non classé » pour un FNB). Sans cette
table, une exclusion (« Exclure » les fossiles -> exclude_sector Energy) ne voit pas les pétrolières de VDY.TO.
Le backend lit ce fichier au chargement du dataset (data.load_exposures) et compte chaque FNB au prorata.

- secteur : yfinance `funds_data.sector_weightings` (part de la poche actions) x `asset_classes.stockPosition`,
  libellés ramenés aux secteurs GICS des actions de l'univers. À défaut, le `category_group` du FNB s'il nomme un
  secteur. Un FNB d'obligations, de matières premières ou de crypto n'a donc aucune exposition sectorielle.
- pays : table statique COUNTRIES ci-dessous (ordres de grandeur tirés des fiches des émetteurs, 2025-2026; seuls
  les pays d'au moins ~2 % sont listés, le reste n'est attribué à aucun pays).

Usage (depuis la racine du dépôt, après build_universe.py):

    python data-prep/build_etf_exposures.py
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ROOT / "backend" / "data" / "universe.parquet"
OUT = ROOT / "backend" / "src" / "invest_agents" / "etf_exposures.csv"

# Secteurs yfinance (Morningstar) -> secteurs GICS de financedatabase (colonne `sector` des actions).
YF_SECTORS = {
    "realestate": "Real Estate",
    "consumer_cyclical": "Consumer Discretionary",
    "basic_materials": "Materials",
    "consumer_defensive": "Consumer Staples",
    "technology": "Information Technology",
    "communication_services": "Communication Services",
    "financial_services": "Financials",
    "utilities": "Utilities",
    "industrials": "Industrials",
    "energy": "Energy",
    "healthcare": "Health Care",
}
GICS = set(YF_SECTORS.values())

US = {"United States": 1.0}
CA = {"Canada": 1.0}
COUNTRIES: dict[str, dict[str, float]] = {
    # Obligations
    **{s: CA for s in ("CLF.TO", "CLG.TO", "VGV.TO", "XRB.TO", "XCB.TO", "XBB.TO")},
    **{s: US for s in ("AGZ", "GOVT", "IEF")},
    "BND": {"United States": 0.94},
    "LQD": {"United States": 0.85, "United Kingdom": 0.04, "Canada": 0.03, "Japan": 0.02},
    "HYG": {"United States": 0.86, "Canada": 0.05, "United Kingdom": 0.02},
    # Mixte (iShares Core Allocation: actions mondiales + obligations surtout américaines)
    "AOK": {"United States": 0.78, "Japan": 0.03, "United Kingdom": 0.02, "France": 0.02, "Germany": 0.02, "Canada": 0.02},
    "AOM": {"United States": 0.75, "Japan": 0.04, "United Kingdom": 0.03, "France": 0.02, "Germany": 0.02, "Canada": 0.02},
    "AOR": {"United States": 0.70, "Japan": 0.05, "United Kingdom": 0.03, "France": 0.02, "Germany": 0.02, "Canada": 0.02,
            "China": 0.02},
    "AOA": {"United States": 0.66, "Japan": 0.06, "United Kingdom": 0.04, "France": 0.03, "Germany": 0.02, "China": 0.02,
            "Canada": 0.02},
    # Actions - marchés
    **{s: US for s in ("SPY", "IYY", "IWM", "DIA", "ESGU", "ITA", "SHLD", "MSOS")},
    "QQQ": {"United States": 0.97},
    **{s: CA for s in ("XIU.TO", "XIC.TO", "VDY.TO", "XESG.TO", "XFN.TO", "XEG.TO", "XIT.TO", "XMA.TO", "XRE.TO",
                       "XUT.TO")},
    "EWU": {"United Kingdom": 1.0},
    "DAX": {"Germany": 1.0},
    "EWG": {"Germany": 1.0},
    "EWQ": {"France": 1.0},
    "EWJ": {"Japan": 1.0},
    "JPXN": {"Japan": 1.0},
    "EWY": {"South Korea": 1.0},
    "MCHI": {"China": 1.0},
    "INDA": {"India": 1.0},
    "EWZ": {"Brazil": 1.0},
    "EWW": {"Mexico": 1.0},
    "VGK": {"United Kingdom": 0.23, "France": 0.15, "Switzerland": 0.14, "Germany": 0.14, "Netherlands": 0.07,
            "Spain": 0.05, "Italy": 0.05, "Sweden": 0.05, "Denmark": 0.04},
    "ILF": {"Brazil": 0.60, "Mexico": 0.25, "Chile": 0.07, "Peru": 0.05},
    "IPAC": {"Japan": 0.68, "Australia": 0.18, "Hong Kong": 0.06, "Singapore": 0.04},
    "EFA": {"Japan": 0.22, "United Kingdom": 0.15, "France": 0.10, "Switzerland": 0.09, "Germany": 0.09,
            "Australia": 0.07, "Netherlands": 0.05, "Sweden": 0.03, "Denmark": 0.03, "Spain": 0.03, "Italy": 0.03,
            "Hong Kong": 0.02},
    "ACWX": {"Japan": 0.14, "United Kingdom": 0.09, "China": 0.08, "Canada": 0.08, "France": 0.06, "Taiwan": 0.06,
             "Switzerland": 0.06, "Germany": 0.06, "India": 0.05, "Australia": 0.04, "South Korea": 0.03,
             "Netherlands": 0.03},
    "XAW.TO": {"United States": 0.66, "Japan": 0.05, "United Kingdom": 0.03, "China": 0.03, "France": 0.02,
               "Taiwan": 0.02, "Switzerland": 0.02, "Germany": 0.02, "India": 0.02},
    "IOO": {"United States": 0.80, "United Kingdom": 0.04, "Switzerland": 0.03, "Japan": 0.02, "France": 0.02,
            "Germany": 0.02, "Netherlands": 0.02},
    "EEM": {"China": 0.27, "Taiwan": 0.20, "India": 0.18, "South Korea": 0.11, "Brazil": 0.04, "South Africa": 0.03,
            "Saudi Arabia": 0.03, "Mexico": 0.02},
    "EDIV": {"Taiwan": 0.20, "China": 0.15, "Brazil": 0.10, "India": 0.10, "South Africa": 0.06, "Thailand": 0.05,
             "Mexico": 0.05},
    "BKF": {"China": 0.50, "India": 0.35, "Brazil": 0.15},
    # Actions - thèmes
    "XLK": US, "VGT": US,
    "SMH": {"United States": 0.75, "Taiwan": 0.12, "Netherlands": 0.07},
    "DTCR": {"United States": 0.80, "Japan": 0.04, "Australia": 0.03},
    "AIQ": {"United States": 0.70, "China": 0.07, "Japan": 0.04, "Taiwan": 0.04, "South Korea": 0.03},
    "ICLN": {"United States": 0.40, "China": 0.08, "Denmark": 0.08, "Spain": 0.07, "India": 0.04, "Brazil": 0.04},
    "TAN": {"United States": 0.45, "China": 0.15, "Spain": 0.07, "Germany": 0.04},
    "AQWA": {"United States": 0.60, "United Kingdom": 0.15, "Brazil": 0.05, "Japan": 0.04},
    "BETZ": {"United States": 0.45, "United Kingdom": 0.10, "Sweden": 0.10, "Australia": 0.07},
    "BOTZ": {"United States": 0.45, "Japan": 0.30, "Switzerland": 0.10},
    "ROBO": {"United States": 0.50, "Japan": 0.15, "Germany": 0.05, "Switzerland": 0.04},
    "XT": {"United States": 0.65, "Japan": 0.06, "China": 0.04, "Taiwan": 0.03},
    # Actions - secteurs
    **{s: US for s in ("XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC")},
    "NREA.TO": {"United States": 0.55, "Canada": 0.10, "United Kingdom": 0.07, "Japan": 0.05, "Spain": 0.05,
                "Australia": 0.05},
    # COMT (matières premières) et BITW (crypto): aucun pays.
}


def sector_exposure(symbol: str, category_group: str) -> tuple[dict[str, float], str]:
    """Exposition sectorielle du FNB (fractions du capital) et sa source."""
    import yfinance as yf

    try:
        data = yf.Ticker(symbol).funds_data
        raw = data.sector_weightings or {}
        stock = float((data.asset_classes or {}).get("stockPosition", 0.0))
    except Exception as exc:  # FNB inconnu de yfinance, réseau…
        print(f"  ! {symbol}: yfinance indisponible ({exc})")
        raw, stock = {}, 0.0
    total = sum(float(v) for k, v in raw.items() if k in YF_SECTORS)
    if total > 0 and stock > 0:
        return {YF_SECTORS[k]: stock * float(v) / total for k, v in raw.items() if k in YF_SECTORS}, "yfinance"
    if category_group in GICS:
        return {category_group: 1.0}, "category_group"
    return {}, "aucune"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--universe", type=Path, default=UNIVERSE)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    df = pd.read_parquet(args.universe, columns=["symbol", "instrument_type", "category_group"])
    etfs = df.drop_duplicates("symbol").query("instrument_type == 'ETF'").set_index("symbol")["category_group"]
    missing = sorted(set(etfs.index) - set(COUNTRIES) - {"COMT", "BITW"})
    if missing:
        raise SystemExit(f"Pays inconnus pour {missing}: compléter COUNTRIES")

    rows = []
    for symbol, group in etfs.sort_index().items():
        sectors, source = sector_exposure(symbol, str(group))
        rows += [(symbol, "sector", k, v, source) for k, v in sectors.items() if v >= 0.0005]
        rows += [(symbol, "country", k, v, "table") for k, v in COUNTRIES.get(symbol, {}).items()]
        top = ", ".join(f"{k} {v:.0%}" for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])[:3])
        print(f"{symbol:8} {source:15} {top}")
        time.sleep(0.2)
    out = pd.DataFrame(rows, columns=["symbol", "dimension", "label", "weight", "source"])
    out["weight"] = out["weight"].round(4)
    args.out.write_text(
        "# Expositions des FNB par secteur et par pays (fractions du capital), produites par "
        "data-prep/build_etf_exposures.py.\n" + out.to_csv(index=False)
    )
    print(f"\n{args.out.relative_to(ROOT)}: {out['symbol'].nunique()} FNB, {len(out)} lignes")


if __name__ == "__main__":
    main()
