"""Query the collected data with DuckDB.

All tables are views over the Parquet files, so there is no database file to
keep in sync. From Python:

    from collector.db import connect
    con = connect()
    con.sql("select * from prices_daily where symbol = 'JKH.N0000' order by trade_date").df()

From the command line:

    python -m collector.db "select trade_date, value from index_daily where index_name = 'ASPI'"

Raw tables (one per stored file set):
    prices, indices, sectors, market, companies, announcements,
    financial_reports, prices_history, index_history, macro

Combined views (what the dashboard uses):
    prices_daily  - one row per stock per day: the daily snapshot where we have
                    it, otherwise the backfilled chart history
    index_daily   - ASPI, S&P SL20 and the 20 sector indices, same rule
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

from .collect import DEFAULT_DATA_DIR

TABLES = ["prices", "indices", "sectors", "market", "companies", "prices_history", "index_history", "macro"]
# Announcements and report links are re-sent for several days, so dedupe them.
DEDUPED = {"announcements": "id", "financial_reports": "id"}


def _has(base: Path, name: str) -> bool:
    return any((base / name).glob("*.parquet"))


def connect(data_dir: Path = DEFAULT_DATA_DIR) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    base = data_dir / "parquet"
    present = set()
    for name in TABLES + list(DEDUPED):
        if not _has(base, name):
            continue
        present.add(name)
        glob = (base / name / "*.parquet").as_posix()
        src = f"read_parquet('{glob}', union_by_name=true)"
        if name in DEDUPED:
            key = DEDUPED[name]
            con.execute(
                f"create view {name} as select * exclude (rn) from ("
                f" select *, row_number() over (partition by {key} order by collected_on) rn from {src})"
                f" where rn = 1"
            )
        elif name in ("prices_history", "index_history"):
            # Several backfills can overlap; keep one row per key.
            key = "trade_date, symbol" if name == "prices_history" else "trade_date, index_name"
            con.execute(
                f"create view {name} as select * exclude (rn) from ("
                f" select *, row_number() over (partition by {key} order by trade_date) rn from {src})"
                f" where rn = 1"
            )
        else:
            con.execute(f"create view {name} as select * from {src}")

    _combined_views(con, present)
    return con


def _combined_views(con: duckdb.DuckDBPyConnection, present: set[str]) -> None:
    parts = []
    if "prices" in present:
        parts.append(
            "select trade_date, symbol, open, high, low, close, share_volume, turnover, trades,"
            " 'snapshot' as source from prices"
        )
    if "prices_history" in present:
        anti = "where not exists (select 1 from prices p where p.trade_date = h.trade_date and p.symbol = h.symbol)" \
            if "prices" in present else ""
        parts.append(
            "select trade_date, symbol, null::double as open, high, low, close, share_volume,"
            " close * share_volume as turnover, null::bigint as trades, 'backfill' as source"
            f" from prices_history h {anti}"
        )
    if parts:
        con.execute("create view prices_daily as " + " union all ".join(parts))

    parts = []
    if "indices" in present:
        parts.append("select trade_date, index_name, 'market' as kind, value, 'snapshot' as source from indices")
    if "sectors" in present:
        parts.append(
            "select trade_date, sector as index_name, 'sector' as kind, index_value as value,"
            " 'snapshot' as source from sectors"
        )
    if "index_history" in present:
        have = []
        if "indices" in present:
            have.append("select trade_date, index_name from indices")
        if "sectors" in present:
            have.append("select trade_date, sector from sectors")
        anti = ""
        if have:
            anti = (
                "where not exists (select 1 from ("
                + " union all ".join(have)
                + ") s(d, n) where s.d = h.trade_date and s.n = h.index_name)"
            )
        parts.append(
            f"select trade_date, index_name, kind, value, 'backfill' as source from index_history h {anti}"
        )
    if parts:
        con.execute("create view index_daily as " + " union all ".join(parts))


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    print(connect().sql(sys.argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
