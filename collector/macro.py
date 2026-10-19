"""Macro data from the Central Bank's "Daily Economic Indicators" PDF.

CBSL publishes a one-page PDF for each business day at a predictable URL:
https://www.cbsl.gov.lk/sites/default/files/daily_economic_indicators_YYYYMMDD_e.pdf

From it we read: policy rate (OPR), weekly AWPR, the latest T-bill auction
yields, USD/LKR, NCPI and CCPI inflation, real GDP growth, and Brent/WTI oil.

    python -m collector.macro --days 400     # backfill about a year
    python -m collector.macro                # catch up the last 10 days

Parsing a PDF is fragile, so every value is range-checked; a value that does
not look right is stored as empty rather than wrong. A failure here never
stops the daily stock collection.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import logging
import re
import sys
from pathlib import Path

import httpx
import pandas as pd
import pdfplumber

from .collect import DEFAULT_DATA_DIR, write_table

log = logging.getLogger("collector.macro")

URL = "https://www.cbsl.gov.lk/sites/default/files/daily_economic_indicators_{:%Y%m%d}_e.pdf"
MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], 1)}

# Plausible ranges; anything outside is treated as a parsing mistake.
RANGES = {
    "opr": (2, 30),
    "awpr": (2, 40),
    "tbill_91d": (1, 40),
    "tbill_182d": (1, 40),
    "tbill_364d": (1, 40),
    "usd_buy": (100, 1000),
    "usd_sell": (100, 1000),
    "usd_spot": (100, 1000),
    "ncpi_yoy": (-20, 100),
    "ccpi_yoy": (-20, 100),
    "gdp_growth": (-30, 30),
    "brent": (10, 300),
    "wti": (10, 300),
}


def _f(x: str | None) -> float | None:
    try:
        return float(x.replace(",", "")) if x not in (None, "-") else None
    except ValueError:
        return None


def parse(text: str, day: dt.date) -> dict:
    """Pull the indicators out of the PDF's extracted text."""
    row: dict = {"date": day}

    m = re.search(r"\n(\d+\.\d+)% (\d+\.\d+)%\s*\n", text)
    if m:
        row["opr"], row["awpr"] = _f(m.group(1)), _f(m.group(2))

    # Three lines under the heading: 91, 182 and 364 days. First column is
    # the latest primary auction, second the secondary market (often "-").
    m = re.search(
        r"Yield Rates of T-Bills\s*\(per cent\)\s*(\d{2}-\w{3}-\d{2}) \S+\s*\n"
        r"(\S+) \S+\s*\n(\S+) \S+\s*\n(\S+) \S+",
        text,
    )
    if m:
        row["tbill_auction_date"] = dt.datetime.strptime(m.group(1), "%d-%b-%y").date()
        row["tbill_91d"], row["tbill_182d"], row["tbill_364d"] = (_f(m.group(i)) for i in (2, 3, 4))

    m = re.search(r"USD (\d+\.\d+) (\d+\.\d+)", text)
    if m:
        row["usd_buy"], row["usd_sell"] = _f(m.group(1)), _f(m.group(2))
    m = re.search(r"\n(\d{3}\.\d{2})\n", text)  # indicative USD/LKR spot rate
    if m:
        row["usd_spot"] = _f(m.group(1))

    # e.g. "August2026 8.1% September20268.0%" or "April 2026 4.7% May 20265.5%"
    # The first is NCPI (published later), the second CCPI, per the PDF header.
    m = re.search(r"([A-Z][a-z]+) ?(\d{4}) ?(-?\d+\.\d+)% ([A-Z][a-z]+) ?(\d{4}) ?(-?\d+\.\d+)%", text)
    if m and m.group(1) in MONTHS and m.group(4) in MONTHS:
        row["ncpi_month"] = dt.date(int(m.group(2)), MONTHS[m.group(1)], 1)
        row["ncpi_yoy"] = _f(m.group(3))
        row["ccpi_month"] = dt.date(int(m.group(5)), MONTHS[m.group(4)], 1)
        row["ccpi_yoy"] = _f(m.group(6))

    m = re.search(r"(\d{4})Q([1-4])(-?\d+\.\d+)%", text)
    if m:
        row["gdp_quarter"] = f"{m.group(1)}Q{m.group(2)}"
        row["gdp_growth"] = _f(m.group(3))

    m = re.search(r"Brent WTI OPEC[^\n]*\n(?:[^\n]*\n)??(\d+\.\d+) (\d+\.\d+) (\d+\.\d+)", text)
    if m:
        row["brent"], row["wti"] = _f(m.group(1)), _f(m.group(2))

    for key, (lo, hi) in RANGES.items():
        v = row.get(key)
        if v is not None and not (lo <= v <= hi):
            log.warning("%s: %s=%s outside %s-%s, dropped", day, key, v, lo, hi)
            row[key] = None
    return row


def fetch_day(http: httpx.Client, day: dt.date) -> dict | None:
    resp = http.get(URL.format(day))
    if resp.status_code == 404 or "pdf" not in resp.headers.get("content-type", ""):
        return None  # no report that day (weekend or holiday)
    resp.raise_for_status()
    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    return parse(text, day)


def stored_days(data_dir: Path) -> set[dt.date]:
    return {dt.date.fromisoformat(p.stem) for p in (data_dir / "parquet" / "macro").glob("*.parquet")}


def update(data_dir: Path, days: int = 10, today: dt.date | None = None) -> int:
    """Fetch every missing business day in the last `days` days. Returns rows saved."""
    today = today or dt.date.today()
    have = stored_days(data_dir)
    wanted = [today - dt.timedelta(days=i) for i in range(days, -1, -1)]
    wanted = [d for d in wanted if d.weekday() < 5 and d not in have]
    saved = 0
    with httpx.Client(timeout=45, follow_redirects=True,
                      headers={"User-Agent": "cse-lab/0.1 (personal research)"}) as http:
        for day in wanted:
            try:
                row = fetch_day(http, day)
            except Exception as exc:  # noqa: BLE001 - macro must never break the run
                log.warning("CBSL %s: %s", day, exc)
                continue
            if row is None:
                continue
            write_table(pd.DataFrame([row]), data_dir / "parquet" / "macro" / f"{day:%Y-%m-%d}.parquet")
            saved += 1
    log.info("macro: saved %d new days", saved)
    return saved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Collect CBSL daily economic indicators.")
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    ap.add_argument("--days", type=int, default=10, help="how many days back to fill")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    update(args.data_dir, days=args.days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
