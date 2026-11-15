# Factor scores (`factor_scores.parquet`)

Each of the universe's 721 stocks gets 5 scores that rank it against its peers today. The scores are a
cross-sectional ranking, not a forecast.

- **Notebook:** `factors_model.ipynb`
- **Output:** `data/factor_scores.parquet`, also in `s3://monport-datasets-381491955506/factors/factor_scores.parquet`
- **Data:** stock list from `universe.parquet` (S3), fundamentals from yfinance `Ticker().info`

## Output

One row per stock, 721 rows:

| Column | Description |
|---|---|
| `ticker` | Yahoo ticker, same as `symbol` in `universe.parquet` |
| `asset_class`, `instrument_type` | Always `Equity`, `Stock` |
| `momentum`, `quality`, `value`, `growth`, `size` | Z-scores: 0 = average of the cell, +1 = one standard deviation better |

The most positive score is the best stock of its cell. No value is null.

## Metrics

Every metric is oriented so that **higher = better**.

| Factor | Metrics | yfinance fields |
|---|---|---|
| Momentum | 12-month price change; distance above the 200-day average | `fiftyTwoWeekChangePercent`, `twoHundredDayAverageChangePercent` |
| Quality | ROA; operating margin; −debt/equity; FCF margin | `returnOnAssets`, `operatingMargins`, `debtToEquity`, `freeCashflow / totalRevenue` |
| Value | Forward E/P; B/P; S/P; EBITDA/EV | 1 / `forwardPE`, `priceToBook`, `priceToSalesTrailing12Months`, `enterpriseToEbitda` |
| Growth | Revenue growth; earnings growth; expected EPS growth | `revenueGrowth`, `earningsGrowth`, `forwardEps / trailingEps − 1` |
| Size | log(market cap) | `marketCap` |

The metric list was trimmed to avoid overlap. ROE and gross margin duplicate ROA and operating margin, and
trailing E/P is about 0.9 correlated with forward E/P, so those were dropped.

## Method

1. **Cells.** A cell is a listing market (United States, Canada, France) × GICS sector. The listing market is used
   instead of the country of domicile because several domicile countries have only 1 to 4 stocks, and the market
   matches the currency of the ratios.
2. **Winsorize.** Each metric is capped at its 1st and 99th percentiles across all stocks.
3. **Z-score per metric.** Each metric is z-scored within its cell. If a cell has fewer than 5 stocks with data for
   that metric, the metric is z-scored across the whole market instead.
4. **Combine.** Momentum, quality, value and growth are each the simple average (1/n) of their available metric
   z-scores, re-z-scored within the same cell.
5. **Size.** log(market cap) z-scored within the listing market only. A larger company scores higher.
6. **Missing data.** A stock missing one metric is averaged over the metrics it has. A stock with no data at all
   for a factor gets 0 (neutral).

### Special cases

- **Negative equity** (36 stocks such as MO, MCD, VRSN, ABBV): Yahoo leaves debt/equity blank, so these stocks get
  the **worst** leverage value. Skipping the blank would have rewarded them with no leverage penalty.
- **Negative earnings or book value:** a negative E/P or B/P is kept, so the stock correctly ranks as expensive.
- **Expected EPS growth** is only computed when trailing EPS is positive.

## Checks

- **Coverage:** every metric covers at least 89% of stocks. The lowest are earnings growth (89%) and debt/equity
  (90%); both momentum metrics cover 100%.
- **Correlation between factors:** all |ρ| ≤ 0.30. The largest is value vs size (−0.30): large caps tend to be
  expensive.
- **Top names look sensible.** For example:
  - Quality: MA and V.
  - Cheapest on value: SMCI and UAL.
  - Most expensive on value: uranium names (NXE.TO, DML.TO).
  - Largest on size: AAPL, NVDA and MSFT.

## Limits

- **Snapshot.** The scores use today's yfinance data, so they can't be used in a historical backtest without
  look-ahead.
- **Data quality.** Yahoo's fundamentals are free data with occasional gaps and errors, and their reporting dates
  differ by company.
- **Momentum is price-only.** It excludes dividends and includes the most recent month, which the usual momentum
  definition skips.
- **Small cells are noisy.** Some cells hold very few stocks (e.g. French Energy, Canadian Health Care). The
  fallback to the whole market only applies below 5 stocks per metric.
- **Sector-relative.** A score compares a stock to its own sector. A "cheap" tech stock can still be expensive
  compared with a bank.
- **Ratios mean different things across sectors.** Debt/equity and EBITDA/EV make little sense for banks and
  insurers. Those values are often missing, so the factor relies on the other metrics.
- **Size direction.** Large = positive. If the size score should represent the small-cap premium (the frontend's
  "taille" factor), flip its sign.
- **Equal weights.** Metrics within a factor are equally weighted, with no optimization or backtest behind the
  choice.
- **Stocks only.** ETFs and crypto get no scores.

## Rerun

Run `factors_model.ipynb` from top to bottom.

- yfinance responses are cached in `data/factors_info_cache.json`, and only missing tickers are fetched. Delete the file
  to refresh the data. A full fetch makes one request per stock, 721 in total.
- The parameters are at the top of section 4: `CELL`, `FALLBACK`, `MIN_CELL = 5` and `WINSOR = (0.01, 0.99)`.
- The metric list is the `FACTORS` dictionary in section 3.
