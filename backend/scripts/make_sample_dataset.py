"""Génère un dataset SYNTHÉTIQUE pour le développement local (prix inventés, aucune donnée réelle).

Il imite la sortie de `create_opt_inputs` (data-prep/Universe_Cleaned.ipynb): mêmes FNB et cryptos que
le notebook, des actions canadiennes, américaines et françaises, et la même période (depuis 2026-01-01).
Le vrai dataset s'exporte depuis le notebook:

    opt.to_parquet("backend/data/universe.parquet")
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "data" / "universe.parquet"

# (symbole, nom, devise, category_group, mu, vol, bêta)
ETFS = [
    ("SPY", "SPDR S&P 500 ETF Trust", "USD", "Equities", 0.10, 0.15, 1.0),
    ("IYY", "iShares Dow Jones U.S. ETF", "USD", "Equities", 0.10, 0.15, 1.0),
    ("IWM", "iShares Russell 2000 ETF", "USD", "Equities", 0.08, 0.21, 1.2),
    ("EFA", "iShares MSCI EAFE ETF", "USD", "Equities", 0.07, 0.14, 0.8),
    ("ACWX", "iShares MSCI ACWI ex U.S. ETF", "USD", "Equities", 0.07, 0.14, 0.8),
    ("IOO", "iShares Global 100 ETF", "USD", "Equities", 0.09, 0.14, 0.95),
    ("EEM", "iShares MSCI Emerging Markets ETF", "USD", "Equities", 0.08, 0.19, 0.9),
    ("ILF", "iShares Latin America 40 ETF", "USD", "Equities", 0.07, 0.24, 0.9),
    ("BKF", "iShares MSCI BIC ETF", "USD", "Equities", 0.06, 0.22, 0.8),
    ("EDIV", "SPDR S&P Emerging Markets Dividend ETF", "USD", "Equities", 0.07, 0.16, 0.7),
    ("AIBF", "iShares Future AI Beneficiaries ETF", "USD", "Equities", 0.14, 0.26, 1.4),
    ("AQWA", "Global X Clean Water ETF", "USD", "Equities", 0.07, 0.17, 0.9),
    ("AOA", "iShares Core Aggressive Allocation ETF", "USD", "Equities", 0.08, 0.12, 0.8),
    ("AOR", "iShares Core Growth Allocation ETF", "USD", "Equities", 0.07, 0.10, 0.65),
    ("AOM", "iShares Core Moderate Allocation ETF", "USD", "Equities", 0.055, 0.07, 0.45),
    ("AOK", "iShares Core Conservative Allocation ETF", "USD", "Equities", 0.045, 0.055, 0.35),
    ("VDY.TO", "Vanguard FTSE Canadian High Dividend Yield Index ETF", "CAD", "Equities", 0.08, 0.13, 0.85),
    ("DACL.TO", "Desjardins Canadian Low Carbon Index ETF", "CAD", "Equities", 0.075, 0.13, 0.9),
    ("DACU.TO", "Desjardins American Low Carbon Index ETF", "CAD", "Equities", 0.09, 0.15, 1.0),
    ("DAGL.TO", "Desjardins Global Low Carbon Index ETF", "CAD", "Equities", 0.08, 0.14, 0.95),
    ("KORX.TO", "Korea Technology Index ETF", "CAD", "Equities", 0.11, 0.25, 1.2),
    ("NSGE.TO", "NBI Sustainable Global Equity ETF", "CAD", "Equities", 0.08, 0.14, 0.95),
    ("NTHM.TO", "NBI Global Diversified Thematic ETF", "CAD", "Equities", 0.09, 0.17, 1.05),
    ("NREA.TO", "NBI Global Real Assets Income ETF", "CAD", "Equities", 0.06, 0.14, 0.7),
    ("AGZ", "iShares Agency Bond ETF", "USD", "Fixed Income", 0.035, 0.04, 0.05),
    ("VGV.TO", "Vanguard Canadian Government Bond Index ETF", "CAD", "Fixed Income", 0.03, 0.05, 0.05),
    ("CLF.TO", "iShares 1-5 Year Laddered Government Bond Index ETF", "CAD", "Fixed Income", 0.03, 0.025, 0.02),
    ("CLG.TO", "iShares 1-10 Year Laddered Government Bond Index ETF", "CAD", "Fixed Income", 0.033, 0.04, 0.03),
    ("COMT", "iShares GSCI Commodity Dynamic Roll Strategy ETF", "USD", "Commodities", 0.05, 0.18, 0.3),
]
CRYPTO = [("BTC-CAD", "Bitcoin CAD", 0.35, 0.55, 1.4), ("ETH-CAD", "Ethereum CAD", 0.40, 0.70, 1.7)]
STOCK_SECTORS = {
    "Information Technology": (0.15, 0.30), "Financials": (0.09, 0.19), "Health Care": (0.08, 0.20),
    "Energy": (0.09, 0.28), "Utilities": (0.05, 0.15), "Consumer Staples": (0.06, 0.14),
    "Consumer Discretionary": (0.09, 0.24), "Industrials": (0.09, 0.20), "Materials": (0.08, 0.24),
    "Communication Services": (0.10, 0.25), "Real Estate": (0.06, 0.20),
}
COUNTRIES = [("United States", "USD", "", 0.55), ("Canada", "CAD", ".TO", 0.35), ("France", "EUR", ".PA", 0.10)]


def main(seed: int = 7) -> None:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2026-01-01", "2026-11-10")
    n = len(dates)
    market = rng.normal(0.00035, 0.0085, n)
    factor = {s: rng.normal(0, 0.005, n) for s in STOCK_SECTORS}
    rows = []

    def add(symbol, meta, mu, vol, beta, extra=None):
        idio = rng.normal(0, vol / np.sqrt(252) * 0.6, n)
        r = mu / 252 + beta * market + (extra if extra is not None else 0) + idio
        rows.append(pd.DataFrame({"date": dates, "symbol": symbol, "total_return_cad": r,
                                  "is_included_universe": True, **meta}))

    for sym, name, cur, group, mu, vol, beta in ETFS:
        add(sym, {"name": name, "currency": cur, "instrument_type": "ETF", "asset_class": group}, mu, vol, beta)
    for sym, name, mu, vol, beta in CRYPTO:
        add(sym, {"name": name, "currency": "CAD", "instrument_type": "Cryptocurrency", "asset_class": "Alternative"},
            mu, vol, beta)
    i = 0
    for sector, (mu_hi, vol_hi) in STOCK_SECTORS.items():
        for k in range(6):
            country, cur, suffix, _ = COUNTRIES[rng.choice(3, p=[c[3] for c in COUNTRIES])]
            i += 1
            add(f"SYN{i:03d}{suffix}",
                {"name": f"Synthetic {sector} Corp {k + 1}", "currency": cur, "instrument_type": "Stock",
                 "asset_class": "Equity", "sector": sector, "country": country},
                rng.uniform(0.02, mu_hi), rng.uniform(vol_hi * 0.7, vol_hi * 1.2), rng.uniform(0.6, 1.4),
                factor[sector])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df = pd.concat(rows, ignore_index=True)
    df.to_parquet(OUT, index=False)
    print(f"{df['symbol'].nunique()} actifs, {n} dates, {len(df):,} lignes -> {OUT}")


if __name__ == "__main__":
    main()
