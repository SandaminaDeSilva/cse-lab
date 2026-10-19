"""One-off backfill of about a year of daily history from the CSE chart API.

The daily collector only sees today, so this fills in the past year that the
cse.lk charts expose:

    python -m collector.history

- Stocks: companyChartDataByStock?stockId=<id>&period=5 -> daily close,
  high, low and volume (no open price) for roughly the last 12 months.
- Indices and sectors: chartData?chartId=<id>&period=5 -> daily level.

Backfilled rows live in their own tables (prices_history, index_history).
The views in collector.db prefer the full daily snapshot wherever both exist.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

import pandas as pd

from . import transform
from .client import CSEClient, NonRetryableError
from .collect import DEFAULT_DATA_DIR, write_raw, write_table

log = logging.getLogger("collector.history")

YEAR_PERIOD = 5  # the chart API's "1 year" setting
ASPI_CHART_ID = 1
SPSL_CHART_ID = 40


def stock_history(client: CSEClient, securities: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """securities: columns symbol, security_id (from the latest prices table)."""
    rows, raw = [], {}
    for n, (symbol, sec_id) in enumerate(securities[["symbol", "security_id"]].itertuples(index=False), 1):
        try:
            resp = client.fetch("companyChartDataByStock", params={"stockId": int(sec_id), "period": YEAR_PERIOD})
        except NonRetryableError:
            log.warning("no chart data for %s", symbol)
            continue
        raw[symbol] = resp
        for r in resp.get("chartData") or []:
            rows.append(
                {
                    "trade_date": transform.ms_to_date(r.get("t")),
                    "symbol": symbol,
                    "high": r.get("h"),
                    "low": r.get("l"),
                    "close": r.get("p"),
                    "share_volume": r.get("q"),
                }
            )
        if n % 50 == 0:
            log.info("stock history: %d/%d", n, len(securities))
    return pd.DataFrame(rows), raw


def index_history(client: CSEClient, sectors: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """sectors: columns sector, sector_id (CSE's numeric sector id, e.g. 223)."""
    targets = [("ASPI", ASPI_CHART_ID), ("S&P SL20", SPSL_CHART_ID)]
    targets += [(r.sector, int(r.sector_id)) for r in sectors.itertuples(index=False)]
    rows, raw = [], {}
    for name, chart_id in targets:
        resp = client.fetch("chartData", params={"chartId": chart_id, "period": YEAR_PERIOD})
        raw[name] = resp
        series = {}
        # Several points can share a day; keep the last one (closest to the close).
        for r in sorted(resp or [], key=lambda x: x.get("d") or 0):
            day = transform.ms_to_date(r.get("d"))
            if day is not None and r.get("v") is not None:
                series[day] = r["v"]
        for day, value in series.items():
            rows.append(
                {
                    "trade_date": day,
                    "index_name": name,
                    "kind": "market" if chart_id in (ASPI_CHART_ID, SPSL_CHART_ID) else "sector",
                    "value": value,
                }
            )
    return pd.DataFrame(rows), raw


def run(data_dir: Path) -> int:
    prices_files = sorted((data_dir / "parquet" / "prices").glob("*.parquet"))
    if not prices_files:
        log.error("run the daily collector once first; it provides the list of stocks")
        return 1
    latest = pd.read_parquet(prices_files[-1])
    today = dt.date.fromisoformat(prices_files[-1].stem)

    with CSEClient() as client:
        levels = transform._flatten(client.fetch("marketIndices"))
        sectors = pd.DataFrame([{"sector": r["name"], "sector_id": r["sectorId"]} for r in levels])

        log.info("backfilling %d stocks", len(latest))
        stocks, stocks_raw = stock_history(client, latest)
        log.info("backfilling %d indices", len(sectors) + 2)
        indices, indices_raw = index_history(client, sectors)

    folder = data_dir / "raw" / "backfill" / f"{today:%Y-%m-%d}"
    write_raw(folder, "companyChartDataByStock", stocks_raw)
    write_raw(folder, "chartData", indices_raw)
    write_table(stocks, data_dir / "parquet" / "prices_history" / f"backfill_{today:%Y-%m-%d}.parquet")
    write_table(indices, data_dir / "parquet" / "index_history" / f"backfill_{today:%Y-%m-%d}.parquet")
    log.info(
        "saved %d stock-days (%s to %s) and %d index-days",
        len(stocks),
        stocks["trade_date"].min(),
        stocks["trade_date"].max(),
        len(indices),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Backfill about a year of CSE history.")
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return run(args.data_dir)


if __name__ == "__main__":
    sys.exit(main())
