"""Génère un dataset SYNTHÉTIQUE pour le développement local (aucune donnée réelle).

Le vrai dataset vient de `create_opt_inputs` dans Universe_Cleaned.ipynb. Il suffit de l'exporter:

    df.to_parquet("backend/data/universe.parquet")

Les colonnes utilisées: date, symbol, total_return_cad, name, sector, industry, country, currency,
asset_class, instrument_type, market, is_included_universe.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "data" / "universe.parquet"

SECTORS = {
    "Technology": (0.16, 0.30),
    "Financials": (0.09, 0.20),
    "Health Care": (0.08, 0.18),
    "Energy": (0.10, 0.28),
    "Utilities": (0.05, 0.14),
    "Consumer Staples": (0.06, 0.13),
    "Industrials": (0.09, 0.19),
    "Materials": (0.08, 0.22),
    "Communication Services": (0.10, 0.24),
}
COUNTRIES = [("Canada", "CAD", 0.35), ("United States", "USD", 0.5), ("France", "EUR", 0.15)]


def main(seed: int = 7, n_days: int = 780) -> None:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-11-13", periods=n_days)
    market = rng.normal(0.00035, 0.0085, n_days)
    sector_factor = {s: rng.normal(0, 0.005, n_days) for s in SECTORS}

    rows = []

    def add(symbol, name, sector, country, currency, asset_class, instrument, mu, vol, beta, sf):
        idio = rng.normal(0, vol / np.sqrt(252) * 0.6, n_days)
        r = mu / 252 + beta * market + (sector_factor[sector] if sf else 0) + idio
        rows.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "symbol": symbol,
                    "name": name,
                    "sector": sector,
                    "industry": f"{sector} - général",
                    "country": country,
                    "currency": currency,
                    "asset_class": asset_class,
                    "instrument_type": instrument,
                    "market": "SYNTHETIC",
                    "total_return_cad": r,
                    "is_included_universe": True,
                }
            )
        )

    i = 0
    for sector, (mu_hi, vol_hi) in SECTORS.items():
        for k in range(8):
            country, cur, _ = COUNTRIES[rng.choice(3, p=[c[2] for c in COUNTRIES])]
            i += 1
            add(f"SYN{i:03d}" + (".TO" if country == "Canada" else ""), f"Synthetic {sector} Co {k + 1}",
                sector, country, cur, "Equity", "Stock",
                mu=rng.uniform(0.02, mu_hi), vol=rng.uniform(vol_hi * 0.6, vol_hi * 1.2),
                beta=rng.uniform(0.5, 1.4), sf=True)
    for k, (name, mu, vol, beta) in enumerate(
        [("Synthetic Canada Broad ETF", 0.07, 0.13, 0.9), ("Synthetic US Broad ETF", 0.09, 0.15, 1.0),
         ("Synthetic Global Bond ETF", 0.035, 0.05, 0.1), ("Synthetic Dividend ETF", 0.06, 0.11, 0.7),
         ("Synthetic Gold ETF", 0.05, 0.14, 0.05)]
    ):
        add(f"SETF{k + 1}", name, "Non classé", "Canada" if k % 2 == 0 else "United States", "CAD",
            "ETF", "ETF", mu, vol, beta, sf=False)
    for k, (name, mu, vol, beta) in enumerate(
        [("Synthetic Bitcoin", 0.35, 0.65, 1.6), ("Synthetic Ether", 0.40, 0.80, 1.9)]
    ):
        add(f"SCRY{k + 1}-CAD", name, "Non classé", "Non classé", "CAD", "Crypto", "Cryptocurrency", mu, vol, beta, sf=False)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df = pd.concat(rows, ignore_index=True)
    df.to_parquet(OUT, index=False)
    print(f"{df['symbol'].nunique()} actifs, {len(df):,} lignes -> {OUT}")


if __name__ == "__main__":
    main()
