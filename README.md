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

## Data source

The public JSON API behind www.cse.lk (`https://www.cse.lk/api/...`). It is undocumented and may change; the collector keeps its request rate low and identifies itself in its User-Agent.
