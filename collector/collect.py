"""Collect today's CSE snapshot and store it.

Run after the market closes (14:30 Colombo time):

    python -m collector.collect

What it does:
1. Pulls the daily endpoints (prices, indices, sectors, market flows,
   breadth, announcements, financial-report links).
2. Works out which trading day the data belongs to. If that day is already
   stored (weekend, holiday, or a second run), it stops without changes.
3. Saves every response untouched as gzipped JSON under data/raw/ so the
   tables can always be rebuilt.
4. Builds tidy tables and saves one Parquet file per table per day under
   data/parquet/.
5. Once a week it also pulls a per-company snapshot (beta, 52-week range,
   foreign holding, shares issued).
6. Runs sanity checks; errors make the run fail so GitHub emails you.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from . import transform, validate
from .client import CSEClient, NonRetryableError

log = logging.getLogger("collector")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "data"

DAILY_ENDPOINTS = [
    "marketStatus",
    "marketSummery",
    "aspiData",
    "snpData",
    "tradeSummary",
    "dailyMarketSummery",
    "getContributors",
    "marketIndices",
    "GICSSectorSummery",
    "approvedAnnouncement",
    "getFinancialAnnouncement",
]
COMPANY_REFRESH_DAYS = 6  # refresh the per-company snapshot about once a week


# ---------------------------------------------------------------- storage


def raw_dir(data_dir: Path, day: dt.date) -> Path:
    return data_dir / "raw" / f"{day:%Y}" / f"{day:%Y-%m-%d}"


def table_path(data_dir: Path, table: str, day: dt.date) -> Path:
    return data_dir / "parquet" / table / f"{day:%Y-%m-%d}.parquet"


def write_raw(folder: Path, name: str, payload: Any) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    # mtime=0 keeps the file identical if the same payload is written twice.
    with gzip.GzipFile(folder / f"{name}.json.gz", "wb", mtime=0) as fh:
        fh.write(data)


def read_raw(folder: Path) -> dict[str, Any]:
    out = {}
    for f in sorted(folder.glob("*.json.gz")):
        with gzip.open(f, "rb") as fh:
            out[f.name.removesuffix(".json.gz")] = json.loads(fh.read())
    return out


def write_table(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def latest_company_snapshot(data_dir: Path) -> dt.date | None:
    files = sorted((data_dir / "parquet" / "companies").glob("*.parquet"))
    return dt.date.fromisoformat(files[-1].stem) if files else None


# ---------------------------------------------------------------- steps


def fetch_daily(client: CSEClient) -> dict[str, Any]:
    raw = {}
    for ep in DAILY_ENDPOINTS:
        log.info("fetching %s", ep)
        raw[ep] = client.fetch(ep)
    return raw


def fetch_companies(client: CSEClient, symbols: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    failed = []
    for n, sym in enumerate(symbols, 1):
        try:
            out[sym] = client.fetch("companyInfoSummery", params={"symbol": sym})
        except NonRetryableError:
            failed.append(sym)
        if n % 50 == 0:
            log.info("company snapshots: %d/%d", n, len(symbols))
    if failed:
        log.warning("no company data for %d symbols: %s", len(failed), ", ".join(failed[:15]))
    return out


def build_tables(raw: dict[str, Any], day: dt.date) -> dict[str, pd.DataFrame]:
    return {name: fn(raw, day) for name, fn in transform.DAILY_TABLES.items()}


def update_status(data_dir: Path, day: dt.date, tables: dict[str, pd.DataFrame], warnings: list[str]) -> None:
    status_file = data_dir / "status.json"
    status = {
        "last_trade_date": day.isoformat(),
        "collected_at": dt.datetime.now(transform.COLOMBO).isoformat(timespec="seconds"),
        "rows": {name: len(df) for name, df in tables.items()},
        "warnings": warnings,
    }
    status_file.write_text(json.dumps(status, indent=2) + "\n")

    log_file = data_dir / "collection_log.csv"
    new = not log_file.exists()
    with log_file.open("a") as fh:
        if new:
            fh.write("trade_date,collected_at,stocks,warnings\n")
        fh.write(f"{day},{status['collected_at']},{len(tables['prices'])},{len(warnings)}\n")


def rebuild(data_dir: Path) -> int:
    """Rebuild every Parquet table from the raw archive (after a code fix)."""
    days = sorted(p for p in (data_dir / "raw").glob("*/*") if p.is_dir())
    for folder in days:
        day = dt.date.fromisoformat(folder.name)
        raw = read_raw(folder)
        for name, df in build_tables(raw, day).items():
            write_table(df, table_path(data_dir, name, day))
        if "companyInfoSummery" in raw:
            write_table(transform.companies(raw["companyInfoSummery"], day), table_path(data_dir, "companies", day))
        log.info("rebuilt %s", day)
    log.info("rebuilt %d days", len(days))
    return 0


# ---------------------------------------------------------------- main


def run(data_dir: Path, force: bool = False, companies: str = "auto", allow_open: bool = False) -> int:
    with CSEClient() as client:
        status = client.fetch("marketStatus")
        if str(status.get("status", "")).lower() == "market open" and not allow_open:
            log.error("market is still open; run after 14:30 Colombo time (or pass --allow-open)")
            return 2

        raw = fetch_daily(client)
        day = transform.trade_date_of(raw)
        log.info("snapshot belongs to trading day %s", day)

        if table_path(data_dir, "prices", day).exists() and not force:
            log.info("%s is already stored; nothing to do (weekend, holiday or repeat run)", day)
            return 0

        tables = build_tables(raw, day)
        errors, warnings = validate.check(tables)
        for w in warnings:
            log.warning(w)
        if errors:
            for e in errors:
                log.error(e)
            # Keep the raw responses for debugging, but do not write tables.
            write_raw(data_dir / "raw_failed" / f"{day:%Y-%m-%d}", "snapshot", raw)
            return 1

        folder = raw_dir(data_dir, day)
        for name, payload in raw.items():
            write_raw(folder, name, payload)
        for name, df in tables.items():
            write_table(df, table_path(data_dir, name, day))

        last = latest_company_snapshot(data_dir)
        due = last is None or (day - last).days >= COMPANY_REFRESH_DAYS
        if companies == "always" or (companies == "auto" and due):
            symbols = sorted(tables["prices"]["symbol"].dropna().unique())
            log.info("fetching weekly company snapshot for %d symbols", len(symbols))
            company_raw = fetch_companies(client, symbols)
            write_raw(folder, "companyInfoSummery", company_raw)
            write_table(transform.companies(company_raw, day), table_path(data_dir, "companies", day))

        update_status(data_dir, day, tables, warnings)
        log.info(
            "saved %s: %d stocks, %d sectors, %d announcements",
            day,
            len(tables["prices"]),
            len(tables["sectors"]),
            len(tables["announcements"]),
        )
        return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Collect the daily CSE snapshot.")
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    ap.add_argument("--force", action="store_true", help="overwrite a day that is already stored")
    ap.add_argument(
        "--companies",
        choices=["auto", "always", "never"],
        default="auto",
        help="weekly per-company snapshot (auto = when the last one is 6+ days old)",
    )
    ap.add_argument("--allow-open", action="store_true", help="collect even while the market is open")
    ap.add_argument("--rebuild", action="store_true", help="rebuild all tables from data/raw and exit")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is too noisy
    if args.rebuild:
        return rebuild(args.data_dir)
    return run(args.data_dir, force=args.force, companies=args.companies, allow_open=args.allow_open)


if __name__ == "__main__":
    sys.exit(main())
