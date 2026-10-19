"""Query the collected data with DuckDB.

All tables are views over the Parquet files, so there is no database file to
keep in sync. From Python:

    from collector.db import connect
    con = connect()
    con.sql("select * from prices where symbol = 'JKH.N0000' order by trade_date").df()

From the command line:

    python -m collector.db "select trade_date, value from indices where index_name = 'ASPI'"
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

from .collect import DEFAULT_DATA_DIR

TABLES = ["prices", "indices", "sectors", "market", "companies"]
# Announcements and report links are re-sent for several days, so dedupe them.
DEDUPED = {
    "announcements": "id",
    "financial_reports": "id",
}


def connect(data_dir: Path = DEFAULT_DATA_DIR) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    base = data_dir / "parquet"
    for name in TABLES + list(DEDUPED):
        files = base / name
        if not any(files.glob("*.parquet")):
            continue
        glob = (files / "*.parquet").as_posix()
        if name in DEDUPED:
            key = DEDUPED[name]
            con.execute(
                f"create view {name} as select * exclude (rn) from ("
                f" select *, row_number() over (partition by {key} order by collected_on) rn"
                f" from read_parquet('{glob}', union_by_name=true)) where rn = 1"
            )
        else:
            con.execute(f"create view {name} as select * from read_parquet('{glob}', union_by_name=true)")
    return con


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    print(connect().sql(sys.argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
