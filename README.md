# CSE Lab

Personal, information-only research dashboard for the Colombo Stock Exchange.
It reads public market data only and never connects to any CSE, CDS or broker account.

## Phase 1: daily data collector

A GitHub Actions workflow runs every weekday after the market closes and saves that day's data into this repository.

| When (Colombo time) | What |
| --- | --- |
| 15:07 Mon–Fri | Main run |
| 16:22 Mon–Fri | Backup run; does nothing if the main run already saved the day |
| Any time | Manual run: Actions → Collect CSE data → Run workflow |

On weekends and holidays the CSE API still shows the last trading day, so the run sees the day is already stored and exits without changes. If a run fails its checks, GitHub emails you.

### What is collected

| Table | One row per | Main fields |
| --- | --- | --- |
| `prices` | stock per day | open, high, low, close, volume, trades, turnover, crossings, market cap |
| `indices` | index per day | ASPI and S&P SL20 value, high, low, change |
| `sectors` | sector per day | 20 sector indices with turnover, P/E, P/BV, dividend yield |
| `market` | day | turnover, domestic and foreign buying and selling, foreign net, advancers vs decliners |
| `announcements` | announcement | dividends, rights issues, director dealings, AGMs |
| `financial_reports` | report | quarterly and annual report PDF links |
| `companies` | stock per week | shares issued, beta, 52-week and all-time high/low, turnover |

### Where it is stored

```
data/
  raw/YYYY/YYYY-MM-DD/*.json.gz       untouched API responses (the permanent record)
  parquet/<table>/YYYY-MM-DD.parquet  tidy tables built from the raw files
  status.json                         last collected day, row counts, warnings
  collection_log.csv                  one line per collected day
```

If a table-building rule changes, `python -m collector.collect --rebuild` regenerates every table from `data/raw`.

### Querying the data

```bash
pip install -r requirements.txt
python -m collector.db "select trade_date, value from indices where index_name = 'ASPI' order by trade_date"
```

```python
from collector.db import connect
con = connect()
con.sql("select * from prices where symbol = 'JKH.N0000' order by trade_date").df()
```

### Running the collector by hand

```bash
python -m collector.collect                 # collect today (after 14:30 Colombo)
python -m collector.collect --force         # overwrite today's stored data
python -m collector.collect --companies always   # also refresh the per-company snapshot
python -m pytest -q                         # tests against a saved real snapshot
```

### History and macro data

- `python -m collector.history` backfills about one year of daily close, high, low and volume for every stock, plus ASPI, S&P SL20 and the 20 sector indices, from the CSE chart API. Already run once (history from 21 Oct 2025); rerun only if you want to refresh it.
- `python -m collector.macro --days 400` backfills the Central Bank's Daily Economic Indicators: policy rate, AWPR, T-bill auction yields, USD/LKR, CCPI and NCPI inflation, GDP growth, Brent and WTI. The daily collector keeps this up to date automatically.

Views that combine everything: `prices_daily` (snapshot where available, otherwise backfill) and `index_daily`.

## Phase 2: dashboard

A Streamlit website with four pages:

| Page | What it shows |
| --- | --- |
| Market overview | ASPI and S&P SL20, turnover, foreign flows, breadth, sector performance and valuation, top movers, announcements and report links |
| Stock | price with 20/50/200-day averages and Bollinger bands, volume, RSI, MACD, returns, 52-week range, volatility, liquidity, beta, sector P/E, company announcements |
| Screener | every stock filtered by sector, liquidity, RSI, trend, return, sector P/E, market cap; downloadable as CSV |
| Macro | policy rate and T-bill yields, USD/LKR, inflation, real T-bill yield, oil, alongside the ASPI |

Run it on your own computer:

```bash
pip install -r requirements.txt
streamlit run dashboard/app.py
```

### Putting it online (Streamlit Community Cloud, free)

1. Sign in at https://share.streamlit.io with your GitHub account.
2. Create app → choose this repository, branch `main`, main file `dashboard/app.py`.
3. Under Advanced settings, pick Python 3.12, then Deploy.
4. In the app's Settings → Sharing, keep it private so only you can open it.

The app reads the data files in this repository, so it updates on its own as the daily collector commits new data.

## Data sources

- The public JSON API behind www.cse.lk (`https://www.cse.lk/api/...`). It is undocumented and may change; the collector keeps its request rate low and identifies itself in its User-Agent.
- The Central Bank of Sri Lanka's Daily Economic Indicators PDF (`cbsl.gov.lk`). Values are range-checked; anything the parser cannot read reliably is left blank.

Everything here is for personal information only and is not investment advice.
