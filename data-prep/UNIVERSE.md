# Investment universe (`universe.parquet`)

This document explains what `universe.parquet` contains, how it was built, and what to watch for when an
optimizer uses it. It is written for whoever builds the portfolio optimizer.

## 1. Context

The project (MonPort, Datathon 2026, team 20) builds portfolios for a **Canadian retail investor**:

- A questionnaire sets the investor's risk profile.
- The investor can state preferences by asset class, region, theme (e.g. "no weapons", "more clean energy") and
  investment style.
- The backend proposes three portfolios (prudent, balanced, conviction). Each one is a constrained
  mean-variance optimization over the universe.

The optimizer needs two inputs:

1. **Expected returns and a covariance matrix** for every candidate asset, estimated together. That is why the
   universe is **one table covering every asset class**. A separate table per asset class would make
   cross-asset covariance impossible.
2. **Descriptive fields** (asset class, sector, country, theme, …) so constraints like "at most 25% per sector"
   or "exclude theme `vice`" can be written as linear constraints on the weights.

Everything is expressed **in CAD**, the investor's currency. Currency risk on US and European assets is therefore
already part of their returns.

| Item | Value |
|---|---|
| File | `universe.parquet` (≈ 38 MB). The backend's copy is `datathon-pf-2026/backend/data/universe.parquet`. |
| Format | Long: one row per trading day × instrument |
| Rows | 1,167,293 |
| Instruments | 804: 721 stocks, 81 ETFs, 2 cryptocurrencies |
| Dates | 1,527 weekdays, 2021-01-01 → 2026-11-09 |
| Return | Daily **total return in CAD** (dividends reinvested, FX-converted) |
| Built by | `datathon-pf-2026/data-prep/build_universe.py` (script version of the original `Universe_Cleaned.ipynb`) |

---

## 2. Quick start

```python
import pandas as pd

df = pd.read_parquet("universe.parquet")

# Returns matrix: dates × symbols (NaN where an asset doesn't trade that day or isn't listed yet)
R = df.pivot(index="date", columns="symbol", values="total_return_cad")

# One row of metadata per symbol (metadata is constant within a symbol)
meta_cols = ["name", "asset_class", "instrument_type", "currency", "sector", "industry", "country",
             "market", "market_cap", "category_group", "category", "theme"]
meta = df.drop_duplicates("symbol").set_index("symbol")[meta_cols]

# Annualized moments (252 trading days)
mu  = R.mean() * 252
cov = R.cov(min_periods=60) * 252        # pairwise: see section 6.2 before using it as-is
```

---

## 3. What is in the universe

### 3.1 Composition

| `asset_class` | Stock | ETF | Crypto | Examples |
|---|---|---|---|---|
| `Equity` | 721 | 61 | | AAPL, RY.TO, MC.PA; SPY, XIU.TO, XAW.TO, XLK, ICLN |
| `Fixed Income` | | 12 | | XBB.TO, VGV.TO, CLF.TO, BND, GOVT, IEF, LQD, HYG, XRB.TO |
| `Multi-Asset` | | 4 | | AOK, AOM, AOR, AOA (stock and bond mixes) |
| `Real Estate` | | 2 | | XLRE, XRE.TO (45 REIT stocks are `Equity` with `sector = Real Estate`) |
| `Commodities` | | 1 | | COMT |
| `Alternative` | | 1 | 2 | BITW; BTC-CAD, ETH-CAD |

**Stocks** come from three indices: the S&P 500, the S&P/TSX Composite and the CAC 40. Only Mid, Large and Mega
caps are kept (546 Large, 114 Mid, 61 Mega).

- **By country:** United States 484, Canada 171, France 34, Ireland 12, other countries 20 (companies listed in
  the US or Canada but headquartered elsewhere).
- **By sector (GICS):** Industrials 111, Financials 101, Information Technology 95, Materials 77,
  Health Care 65, Consumer Discretionary 64, Energy 50, Utilities 45, Real Estate 45, Consumer Staples 41,
  Communication Services 27.

**Quote currency:** 566 USD, 199 CAD, 39 EUR.

**ETFs** are a hand-picked list:

| Group | ETFs |
|---|---|
| Canadian bonds | CLF.TO, CLG.TO, VGV.TO, XRB.TO, XCB.TO, XBB.TO |
| US bonds | AGZ, GOVT, IEF, LQD, HYG, BND |
| Multi-asset | AOK, AOM, AOR, AOA |
| Country and region markets | SPY, IYY, IWM, QQQ, DIA, XIU.TO, XIC.TO, VDY.TO, EWU, DAX, EWG, EWQ, VGK, EWJ, JPXN, EWY, MCHI, INDA, EWZ, EWW, ILF, IPAC, EFA, ACWX, XAW.TO, IOO, EEM, EDIV, BKF |
| Themes | XLK, VGT, DTCR, AIQ, ITA, SHLD, ESGU, XESG.TO, ICLN, TAN, AQWA, BETZ, MSOS, BOTZ, ROBO, XT |
| Sectors | XLF, XFN.TO, XLE, XEG.TO, XLV, XLI, XLY, XLP, XLU, XUT.TO, XLB, XMA.TO, XLRE, XRE.TO, XLC, XIT.TO, SMH, NREA.TO |
| Commodities and crypto | COMT, BITW |

**Changes to the original ETF list:**

- Recent ETFs without enough history were replaced: DACU.TO → XBB.TO, DACL.TO → XIC.TO, DAGL.TO → XAW.TO and
  NTHM.TO → XT.
- KORX.TO and AIBF were dropped, because EWY and AIQ already cover them.
- NICO was dropped (tobacco is excluded). PM and MO are still in as stocks.
- NSGE.TO was dropped because it rarely traded (see section 5).

### 3.2 Themes

`theme` carries the project's ESG and thematic signal. A numeric ESG score was deliberately not used, because
free ESG data covers equities, ETFs and crypto unevenly. Theme tags apply the same way to all three. They were
curated by hand in `data-prep/themes.csv`. An instrument can have several tags, or none.

| Theme id | Meaning | ETFs | Stocks | Examples |
|---|---|---|---|---|
| `tech` | Technology | 9 | 106 | AAPL, MSFT, XLK, XIT.TO |
| `ia` | AI, data centers, neoclouds, chips | 6 | 43 | NVDA, DLR, VRT, AIQ, DTCR |
| `armement` | Defense and weapons | 2 | 19 | LMT, RTX, CAE.TO, ITA, SHLD |
| `energie-propre` | Renewables, nuclear and uranium, lithium | 2 | 17 | FSLR, NEE, CCO.TO, ICLN, TAN |
| `vice` | Alcohol, tobacco, cannabis, gambling | 2 | 10 | MO, PM, STZ, LVS, BETZ, MSOS |
| `esg` | ESG funds; water, waste and recycling | 3 | 7 | WM, XYL, VIE.PA, ESGU, XESG.TO, AQWA |
| `robotique` | Robotics and automation | 3 | 5 | ISRG, ROK, BOTZ, ROBO, XT |

181 instruments have at least one tag and 623 have none. BTC and ETH have none.

---

## 4. Column reference (`universe.parquet`)

Metadata columns repeat on every row and are the same for every row of a symbol.

| Column | Type | Null? | Description |
|---|---|---|---|
| `date` | datetime64 | never | Trading day, Monday to Friday. 2021-01-01 → 2026-11-09. |
| `symbol` | str | never | Yahoo Finance ticker: `AAPL`, `RY.TO` (Toronto), `MC.PA` (Paris), `BTC-CAD`. |
| `total_return_cad` | float | never | **The return to optimize on.** Simple (not log) daily total return in CAD: `close_price_cad[t] / close_price_cad[t-1] − 1`, where t−1 is the symbol's previous trading day. `0.01` = +1%. |
| `total_return_cad_fwd_1d` | float | last day of each symbol | **For backtests.** The symbol's return on its **next** trading day (`groupby('symbol').shift(-1)`), so the P&L of weights set at the close of day T is `w_T · fwd_1d_T`. It looks one day into the future, so the optimizer must never use it to estimate risk or returns (see 6.6). The backend ignores it. |
| `close_price_loc` | float | never | Adjusted close (splits and dividends) in the quote currency. For auditing. |
| `fx_rate_to_cad` | float | never | CAD per unit of the quote currency on that date. Exactly 1.0 for CAD assets. For auditing. |
| `close_price_cad` | float | never | `close_price_loc × fx_rate_to_cad`. For auditing. |
| `name` | str | never | Instrument name (financedatabase). |
| `asset_class` | str | never | `Equity`, `Fixed Income`, `Multi-Asset`, `Real Estate`, `Commodities`, `Alternative`. |
| `instrument_type` | str | never | `Stock`, `ETF`, `Cryptocurrency`. |
| `currency` | str | never | Quote currency: `USD`, `CAD`, `EUR`. |
| `sector` | str | never | GICS sector, **stocks only**. `Non classé` for ETFs and crypto. |
| `industry` | str | never | GICS industry, **stocks only**. `Non classé` otherwise. |
| `country` | str | never | Company country, **stocks only**. `Non classé` otherwise. |
| `market` | str | non-stocks | Listing exchange: New York Stock Exchange, NASDAQ Global Select, Toronto Stock Exchange, Euronext Paris, … |
| `market_cap` | str | non-stocks | `Mid Cap`, `Large Cap`, `Mega Cap`. |
| `category_group` | str | non-ETFs | The ETF's broad group from financedatabase: `Equities`, `Fixed Income`, or a sector name (`Energy`, `Information Technology`, …). |
| `category` | str | non-ETFs | The ETF's category: `Developed Markets`, `Emerging Markets`, `Government Bonds`, `Allocation`, `REITs`, `Digital Assets`, … |
| `theme` | str | untagged | Theme ids separated by `;`, sorted alphabetically: `ia;tech`, `energie-propre`. See section 3.2. |
| `is_included_universe` | bool | never | Always `True`. Kept for compatibility with the notebook. |

Example rows (some columns omitted):

```
date        symbol   total_return_cad  sector                  country        currency  asset_class  instrument_type  theme
2021-01-04  BTC-CAD   0.092851         Non classé              Non classé     CAD       Alternative  Cryptocurrency   NULL
2021-01-04  ICLN      0.013303         Non classé              Non classé     USD       Equity       ETF              energie-propre
2021-01-04  NVDA      0.002228         Information Technology  United States  USD       Equity       Stock            ia;tech
2021-01-04  RY.TO     0.000861         Financials              Canada         CAD       Equity       Stock            NULL
```

---

## 5. How it was built

```
Wikipedia (S&P 500, S&P/TSX Composite, CAC 40)  ─┐
financedatabase (equities, ETFs, cryptos)        ├─▶ raw/catalog.parquet ──┐
ETF list + manual overrides                       ─┘                        │
yfinance adjusted closes ──────────────────────────▶ raw/prices.parquet ───┼─▶ universe.parquet
yfinance FX (USDCAD=X, EURCAD=X) ──────────────────▶ raw/fx.parquet ───────┤
data-prep/themes.csv (curated theme tags) ─────────────────────────────────┘
```

The methodology is the one in `Universe_Cleaned.ipynb`. Running the notebook's `append_exchange_rates` and
`calculate_returns` functions unchanged on the same prices reproduces every row exactly (zero difference). The
adjustments listed in 5.4 are the only additions.

### 5.1 Catalog: which instruments, with what metadata

1. **Index constituents** are scraped from Wikipedia. Tickers are converted to Yahoo format:
   - S&P 500: `BRK.B` → `BRK-B`.
   - TSX: `CCL.B` → `CCL-B.TO`.
   - CAC 40: `.PA` is appended.
2. **Stock metadata** (name, currency, sector, industry, country, exchange, size) comes from `financedatabase`
   across all exchanges. Only Mid, Large and Mega caps are kept.
3. **ETF metadata** comes from `financedatabase` for the fixed ETF list. Delisted ETFs are excluded.
   - BITW is missing from financedatabase, so its metadata is set by hand: `Digital Assets`, `Alternative`,
     `Bitwise`.
4. **Crypto:** BTC and ETH are quoted directly in CAD (`BTC-CAD`, `ETH-CAD`).
5. `sector`, `industry` and `country` are set to `Non classé` for anything that isn't a stock.
6. **`asset_class` cleanup.** The notebook copied each ETF's `category_group` into `asset_class`. That value mixes
   asset classes with sector names (`Energy`, …) and writes `Equities` where stocks have `Equity`. It is mapped
   to the 6 classes of section 3.1:
   - `Fixed Income`, `Real Estate`, `Commodities` and `Alternative` are kept.
   - `category = Allocation` becomes `Multi-Asset`.
   - Everything else becomes `Equity`.
   - The detail stays in `category_group` and `category`.
7. **`themes.csv` sets the final ticker list.** Catalog symbols missing from it are dropped. That keeps the
   universe stable when the Wikipedia lists change. Four symbols are dropped this way:
   - ARX.TO, BLX.TO and SES.TO were recently added to the TSX and have no prices.
   - NSGE.TO was removed on purpose.

### 5.2 Prices

- yfinance `download(..., auto_adjust=True)`, in chunks of 50 tickers. Adjusted closes include **splits and
  dividends**, so returns are **total returns**.
- Prices start on **2020-12-11**, a three-week burn-in, so each asset's first return in 2021 has a previous close.
- The window ends on 2026-11-09.
- Torex changed its ticker from TXG.TO to **TXR.TO** on 2026-11-03, and yfinance moved its history to the new
  ticker. The new ticker is used.

### 5.3 FX rates

- Rates are the yfinance `USDCAD=X` and `EURCAD=X` closes.
- The series are put on a **calendar-day** index, forward-filled over weekends and holidays, and back-filled at
  the start. This is the notebook's `asfreq('D').ffill().bfill()`.
- Every trading date of every exchange therefore has a rate.
- CAD assets use 1.0.

### 5.4 Returns

The formula is unchanged from the notebook:

```
close_price_cad  = close_price_loc × fx_rate_to_cad              (FX of the same date)
total_return_cad = close_price_cad[t] / close_price_cad[t-1] − 1 (per symbol, over its own trading days)
total_return_cad_fwd_1d = total_return_cad shifted back one day   (per symbol)
```

It is computed **after** these adjustments:

1. **Weekdays only.** Weekend prices are dropped, which only affects crypto, so a Monday crypto return covers
   Friday to Monday. This matters for two reasons:
   - The optimizer annualizes with 252 days. With 7-day crypto data, crypto's annual return would be understated
     by about 30% and its volatility by about 17%.
   - Weekend crypto moves would be missing from every covariance pair.
2. **Burn-in cut.** Rows before 2021-01-01 are dropped once returns are computed.
3. **Bad histories trimmed:**
   - **STLAP.PA** (Stellantis) starts on 2021-01-18. Before that date yfinance carries pre-merger PSA prices on a
     different scale, which created a false +96% day.
   - **SW** (Smurfit WestRock) starts on 2024-07-08, its NYSE listing after the merger. Before that the yfinance
     series is stale: the price is unchanged on 33–59% of days.

### 5.5 Theme join

- `themes.csv` labels are mapped to theme ids:

  | Label | Theme id |
  |---|---|
  | Tech | `tech` |
  | AI | `ia` |
  | Robotics | `robotique` |
  | Clean Energy | `energie-propre` |
  | ESG | `esg` |
  | War | `armement` |
  | Vice | `vice` |

- The ids are joined with `;`, and the column is attached to every row of the symbol.
- An unknown label stops the build.

### 5.6 Validation performed

| Check | Result |
|---|---|
| Duplicate date × symbol rows | none |
| NaN or inf in returns, prices or FX | none |
| Weekend rows | none |
| `close_price_cad = close_price_loc × fx_rate_to_cad` and return = ratio of consecutive CAD closes | exact |
| FX = 1 for CAD assets only. USD/CAD range 1.20–1.47, EUR/CAD range 1.29–1.64 | yes |
| `.TO` assets quoted in CAD, `.PA` assets in EUR | yes |
| Metadata constant per symbol | yes |
| Every symbol has data up to 2026-11-09 | yes |
| No stock or ETF misses more than 5 days of its exchange's calendar | yes |
| Notebook functions reproduce the file | exact match on all rows |
| Fresh yfinance download (AAPL, RY.TO, MC.PA, XBB.TO, BTC-CAD, SPY) | max difference ≈ 3e-7 |
| Near-duplicates correlate | GOOG/GOOGL 0.996, SPY/IYY 0.996, XIU.TO/XIC.TO 0.988, VGT/XLK 0.994 |
| Annual volatility, median by class | Fixed Income 7.8%, Multi-Asset 11.2%, Real Estate 17.6%, Commodities 21.3%, Equity 29.5%, Alternative 71.2% |

Large daily moves (|r| > 40%) were checked one by one and are real events. Examples: MRNA +177% on 2026-08-19
(cancer vaccine trial), CVNA in 2022–2023, GL −53% in April 2024.

A few names have an unchanged price on 5–16% of days:

- MAU.TO and GMIN.TO were thinly traded small caps in 2021–2023 and are normal from 2024.
- CLF.TO and CLG.TO are short-term bond ETFs whose daily move is often smaller than one cent.

This is real trading data and was kept.

---

## 6. Using it in an optimizer: what to watch for

### 6.1 Missing values are structural; don't drop them blindly

`R` (dates × symbols) has NaNs for two reasons:

- **Late listings.** 776 instruments have data from the first week of 2021. The rest start when they were listed
  or after a trim:

  | Symbol | Start |
  |---|---|
  | EXE, CURA.TO, MDA.TO, AQWA, COIN, APP, TFPM.TO, HOOD, DFY.TO | 2021 |
  | CEG, BBUC.TO, BAM.TO, GEHC | 2022 |
  | URW.PA, AAUC.TO, SHLD, VLTO | 2023 |
  | RDDT, SOLV, GEV | 2024-03 |
  | SW | 2024-07 |
  | SOBO.TO | 2024-09 |
  | SNDK | 2025-02 |
  | Q | 2025-10 |
  | FDXF | 2026-05 |
  | HONA | 2026-06 |
  | VYLR | 2026-10 |

  Median history is 1,470 days. The shortest are VYLR with 27 days, then HONA and FDXF, all under 120.
- **Holidays differ by exchange.** US assets trade on 1,470 of the 1,527 dates, Canadian on 1,469, Paris on
  1,500, crypto on all 1,527. A US holiday is a TSX trading day and vice versa. On such a day the closed market
  has no row, and its next return covers two days.

Consequences:

- `R.dropna()` across the whole universe deletes **every date before 2026-10-02**, because of VYLR. Even
  restricted to the 776 assets with full history, it removes 98 dates (6%).
- Don't forward-fill prices to create zero returns. That understates volatility and correlation.
- **Recommended options:**
  - Pairwise statistics, as the backend does (6.2).
  - Or restrict the estimation to a common window and asset set that suits your needs.
- **Very short histories:** exclude assets with too few observations. The backend requires at least 120 days,
  which currently drops FDXF, HONA and VYLR.

### 6.2 Covariance

- `R.cov(min_periods=60)` uses, for each pair, only the dates on which **both** assets have a return. Late
  listings therefore don't shorten anyone else's history.
- The price of that approach: a pairwise matrix is **not guaranteed positive semi-definite**. On this file it has
  16 negative eigenvalues (the most negative is −0.003). A quadratic solver needs a PSD matrix, so project it:
  ```python
  C = cov.fillna(0).to_numpy(); C = (C + C.T) / 2
  vals, vecs = np.linalg.eigh(C)
  C = (vecs * np.clip(vals, 1e-10, None)) @ vecs.T
  ```
  Shrinkage, such as Ledoit–Wolf on a common window, is a good alternative.
- 800 assets against about 1,500 dates makes for a noisy sample covariance. Pre-selecting about 25–60 candidates
  before optimizing, which is what the backend does, keeps the problem well conditioned.
- Near-duplicates are in the universe on purpose: GOOG/GOOGL, NWS/NWSA, FOX/FOXA, SPY/IYY, XIU.TO/XIC.TO,
  VGT/XLK. They are almost perfectly correlated, so don't select both of a pair.

### 6.3 Expected returns

- Annualize as `mean × 252` and `std × √252`. Returns are **simple**, not log.
- The 2021–2026 sample was a strong period for risk assets. Median annual returns by class: Equity 16.7%,
  Alternative 32.5%, Commodities 19.3%, Multi-Asset 8.2%, Real Estate 7.7%, Fixed Income 1.3%.
- Historical means are a very noisy estimate of future returns. Use them with shrinkage toward a long-run
  assumption per class. The backend averages 50/50 with fixed per-class priors: equities 7%, bonds 3.5%, real
  estate 5.5%, gold and commodities 4%, crypto 15%, cash 2.5% (`MU_SHRINK`).
- Short histories (2025–2026 listings) give especially unreliable means.

### 6.4 Things that are *not* in the file

- **Cash.** There is no cash or money-market row. The backend adds a synthetic `CASH-CAD` asset with a constant
  risk-free return and zero volatility.
- **Fees.** There is no `expense_ratio` column. The backend uses defaults: 0.20% for ETFs, 0.40% for crypto, 0%
  for stocks.
- **ETF look-through.** ETFs have no `sector` or `country`. A sector cap therefore only constrains individual
  stocks. To include ETFs in a sector or region limit, use `category_group` and `category`, or map ETFs by hand.
- **Region.** It isn't a column. For stocks, derive it from `country`. For ETFs, use the name or category
  (`Emerging Markets`, …).

### 6.5 Constraint dimensions

| Dimension | Values per symbol | Use |
|---|---|---|
| `asset_class` | exactly 1 | Groups don't overlap, so minimums can be added up. |
| `instrument_type` | exactly 1 | For example "ETFs only" means excluding `Stock`. |
| `sector`, `country` | 1 for stocks; `Non classé` otherwise | Don't treat `Non classé` as a group to cap. |
| `theme` | 0 to 4 | **Groups overlap.** NVDA is in both `ia` and `tech`, so minimum weights across themes cannot be added up. Membership test: `theme` split on `;`. An empty value means no theme, not an "untagged" group. |

Example: the weight of a theme is
`w @ meta.theme.fillna("").str.split(";").apply(lambda t: "vice" in t)`.
Excluding a theme means forcing that mask's weights to 0.

### 6.6 Optimizer vs backtest: which return column

| Use | Column | Rule |
|---|---|---|
| Optimizer (expected returns, covariance) | `total_return_cad` | Use only rows with `date ≤ T` to choose the weights of day T. |
| Backtest (realized P&L) | `total_return_cad_fwd_1d` | The P&L of the weights chosen on day T is `w_T · fwd_1d_T`, the return from T's close to the next close. |

On the same row, `total_return_cad` is known at the close of T and `fwd_1d` only one trading day later, so there
is no look-ahead as long as weights on day T come from `total_return_cad` up to T.

```python
R   = df.pivot(index="date", columns="symbol", values="total_return_cad")         # optimizer input
FWD = df.pivot(index="date", columns="symbol", values="total_return_cad_fwd_1d")  # backtest P&L

port = []
for T in rebalance_dates:                       # or every date
    w = optimize(R.loc[:T])                     # pd.Series of weights indexed by symbol, data up to T only
    port.append((T, (w * FWD.loc[T, w.index]).sum(min_count=1)))
```

Details to handle in the backtest:

- **"Next" is the symbol's next trading day.** 78% of rows point to the following weekday and 18% to the next
  Monday. The other 4% point 2, 4 or 5 days ahead, around holidays. For crypto, Friday's `fwd_1d` is the
  Friday → Monday return (weekends were removed), consistent with the other assets.
- **Exchange holidays.** On a date when an exchange is closed, its symbols have no row, so `FWD` is NaN there.
  That is not a missing return: the move is already in the previous row's `fwd_1d`, which covers both days.
  Treat that NaN as **0** for the held position. Don't drop the date or renormalize the weights, otherwise the
  return is lost or counted twice.
- **Last date.** `fwd_1d` is NaN on 2026-11-09 for every symbol, so the backtest ends on 2026-11-06.
- **Not yet listed.** A symbol with no rows yet can't be held. Restrict the candidates on day T to symbols with
  enough history up to T.
- **Cash.** It's not in the file. If the portfolio holds cash, add its return yourself (risk-free rate / 252 per
  day).
- **Costs.** No fees or trading costs are included. Subtract them separately when weights change.
- **Drift.** `w_T · fwd_1d_T` assumes the portfolio is back at the target weights at every close (daily
  rebalancing). Between less frequent rebalances, let weights drift with returns:
  `w_{t+1} ∝ w_t × (1 + fwd_1d_t)`.

---

## 7. Reference: how the existing backend consumes the file

`build_market` in `datathon-pf-2026/backend/src/invest_agents/data.py`:

1. Keeps rows with `is_included_universe = True`.
2. Pivots `total_return_cad` and drops symbols with fewer than 120 observations, which leaves 801 assets.
3. Adds `CASH-CAD`.
4. Maps `asset_class` to the frontend classes (`classify.py`):
   - `actions`, `obligations`, `immobilier`, `or` (gold and commodities), `crypto`, `liquidites`.
   - Stocks with `sector = Real Estate` become `immobilier`. All other stocks become `actions`.
5. Derives `region` (canada, usa, europe, asie, emergents, or monde for global ETFs). Stocks get it from
   `country`.
6. Builds the theme set:
   - The file's `theme` column decides `tech, ia, robotique, energie-propre, esg, armement, vice`.
   - Keyword rules add `sante, finance, fossiles, consommation, industrie, immobilier`.
7. Computes the moments:
   - `mu = 0.5 × historical mean + 0.5 × class prior`.
   - `cov = pairwise (min_periods = 60) × 252`, then projected to PSD.
8. Exposes the dimensions through `Market.members()`, `Market.groups()` and `Market.allowed_values()`.
   - Constraint types are `exclude_*`, `min_*_weight` and `max_*_weight` for sector, country, asset_class,
     region, theme, factor and instrument_type, plus per-line caps.
   - `optimizer.py` turns them into linear constraints for SciPy.

---

## 8. Intermediate tables (`data-prep/data/raw/`)

These are cached so a rebuild doesn't scrape or download again.

**`catalog.parquet`**: one row per instrument, 808 rows. It still includes the four symbols dropped in step 5.1.

| Column | Description |
|---|---|
| `symbol`, `name`, `currency` | As in the final table. |
| `country`, `sector`, `industry` | Stocks only; `Non classé` otherwise. |
| `market`, `market_cap` | Stocks only. |
| `instrument_type` | `Stock`, `ETF`, `Cryptocurrency`. |
| `asset_class` | **Raw** value (ETFs carry their `category_group`). It is cleaned during the final build. |
| `category_group`, `category`, `family` | ETFs only. `family` is the issuer. |
| `is_included_universe` | Always `True`. |

**`prices.parquet`**: `date, symbol, close_price_loc`. Adjusted closes from 2020-12-11 to 2026-11-09, including
crypto weekends. 1,181,634 rows.

**`prices_missing.parquet`**: `symbol`. Tickers yfinance returned nothing for (ARX.TO, BLX.TO, SES.TO). They
aren't retried on every run.

**`fx.parquet`**: `date, currency, fx_rate_to_cad`. Calendar days, USD and EUR, filled forward. 2,160 days per
currency.

---

## 9. Rebuilding and changing the universe

From the `datathon-pf-2026` folder:

```bash
pip install -r data-prep/requirements.txt
python data-prep/build_universe.py                  # reuses raw/ cache
python data-prep/build_universe.py --refresh all    # re-download everything (or: catalog, prices, fx)
```

The build prints a report: instrument counts, theme counts, the shortest histories, and every daily move above
40% for manual review.

| Change | Where |
|---|---|
| Window (`START_DATE`, `END_DATE`) | top of `build_universe.py` |
| Add or remove an ETF | `ETF_TICKERS` in `build_universe.py` **and** a row in `data-prep/themes.csv` |
| Add or remove a stock | the row in `data-prep/themes.csv` (it must also be in one of the three indices) |
| Change a theme tag | `data-prep/themes.csv` (labels: Tech, AI, Robotics, Clean Energy, ESG, War, Vice) |
| New theme | `THEME_IDS` in `build_universe.py`, plus `classify.THEMES`, `contract.THEME_LABELS` and `frontend/src/data/catalog.ts` |
| Ticker rename / bad early history | `SYMBOL_RENAMES` / `HISTORY_START` in `build_universe.py` |

After rebuilding, `backend/data/universe.parquet` (read by the backend) is the fresh copy. `data-prep/data/universe.parquet` is a convenience copy and is not updated automatically.

---

## 10. Known limitations

- **Survivorship bias.** The stocks are **today's** index members. Their 2021–2026 history excludes companies
  that left the indices, which flatters historical returns.
- **Closing times differ.** Paris, Toronto, New York and the FX rates close at different hours. Same-day
  correlations between Paris and North American assets are slightly understated.
- **Holiday mismatch.** On a holiday of one exchange, that market's next return covers two days (section 6.1).
- **Theme tags are judgment calls.** For example, the defense arms of Boeing and Airbus count as `armement`, and
  LVMH is not tagged `vice`. They can be edited in `themes.csv`.
- **Short histories.** Recent listings (Q, SNDK, FDXF, HONA, VYLR) have unreliable statistics.
