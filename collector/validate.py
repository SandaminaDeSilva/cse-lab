"""Sanity checks on a day's tables before they are saved.

Problems are split into errors (the snapshot is unusable, so the run fails
and GitHub emails you) and warnings (worth a look, saved anyway).
"""

from __future__ import annotations

import pandas as pd

MIN_STOCKS = 150  # a normal day has ~280 rows; far fewer means a broken response


def check(tables: dict[str, pd.DataFrame]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    p = tables.get("prices", pd.DataFrame())
    if len(p) < MIN_STOCKS:
        errors.append(f"prices: only {len(p)} rows (expected at least {MIN_STOCKS})")
    else:
        if p["symbol"].duplicated().any():
            errors.append("prices: duplicate symbols")
        bad = p[(p["close"].isna()) | (p["close"] <= 0)]
        if len(bad):
            warnings.append(f"prices: {len(bad)} rows with missing or non-positive close")
        # Rights entitlements (.R0000) swing wildly by nature, so skip them here.
        ordinary = p[~p["symbol"].str.contains(r"\.R\d", regex=True, na=False)]
        jump = ordinary[
            (ordinary["previous_close"] > 0) & ((ordinary["close"] / ordinary["previous_close"] - 1).abs() > 0.5)
        ]
        if len(jump):
            warnings.append(
                "prices: >50% one-day move (check for splits or rights issues): "
                + ", ".join(jump["symbol"].head(10))
            )

    i = tables.get("indices", pd.DataFrame())
    if i.empty or "ASPI" not in set(i["index_name"]):
        errors.append("indices: ASPI missing")
    elif (i["value"] <= 0).any():
        errors.append("indices: non-positive index value")

    s = tables.get("sectors", pd.DataFrame())
    if len(s) < 15:
        warnings.append(f"sectors: only {len(s)} rows (expected 20)")

    m = tables.get("market", pd.DataFrame())
    if m.empty or pd.isna(m["turnover"].iloc[0]):
        warnings.append("market: turnover missing")

    return errors, warnings
