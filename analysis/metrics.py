"""Per-stock summary metrics used by the screener and stock pages."""

from __future__ import annotations

import duckdb
import pandas as pd

from . import indicators as ind

# Approximate trading-day counts for each lookback.
PERIODS = {"ret_1w": 5, "ret_1m": 21, "ret_3m": 63, "ret_6m": 126, "ret_12m": 240}


def history(con: duckdb.DuckDBPyConnection, symbol: str) -> pd.DataFrame:
    df = con.execute(
        "select * from prices_daily where symbol = ? order by trade_date", [symbol]
    ).df()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


def all_history(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    df = con.sql(
        "select trade_date, symbol, high, low, close, share_volume, turnover from prices_daily"
        " where close > 0 order by symbol, trade_date"
    ).df()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


def stock_metrics(hist: pd.DataFrame) -> dict:
    """Metrics for one stock from its daily history (oldest first)."""
    c = hist["close"].astype(float)
    last = c.iloc[-1]
    out: dict = {
        "close": last,
        "last_trade_date": hist["trade_date"].iloc[-1].date(),
        "days_of_history": len(hist),
        "chg_1d": ind.pct_return(c, 1),
    }
    for name, n in PERIODS.items():
        out[name] = ind.pct_return(c, n)
    out["rsi_14"] = _last(ind.rsi(c, 14))
    for n in (50, 200):
        avg = _last(ind.sma(c, n))
        out[f"vs_sma_{n}"] = (last / avg - 1) if avg else None
    out["volatility_60d"] = ind.volatility(c, 60)
    window = hist.tail(240)
    hi, lo = window["high"].max(), window["low"].min()
    out["high_52w"], out["low_52w"] = hi, lo
    out["from_52w_high"] = (last / hi - 1) if hi else None
    out["avg_turnover_20d"] = hist["turnover"].tail(20).mean()
    return out


def _last(s: pd.Series) -> float | None:
    s = s.dropna()
    return float(s.iloc[-1]) if len(s) else None


def screener_table(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per stock: returns, trend, momentum, liquidity, size, sector."""
    hist = all_history(con)
    rows = []
    for symbol, g in hist.groupby("symbol", sort=False):
        if len(g) < 2:
            continue
        rows.append({"symbol": symbol, **stock_metrics(g)})
    table = pd.DataFrame(rows)

    latest = con.sql(
        "select symbol, name, market_cap from prices"
        " where trade_date = (select max(trade_date) from prices)"
    ).df()
    table = table.merge(latest, on="symbol", how="left")

    try:
        comp = con.sql(
            "select symbol, sector, beta_aspi from companies"
            " qualify row_number() over (partition by symbol order by as_of desc) = 1"
        ).df()
        table = table.merge(comp, on="symbol", how="left")
    except duckdb.Error:
        table["sector"], table["beta_aspi"] = None, None

    # Sector valuation (the CSE publishes P/E, P/BV and yield per sector, not per stock).
    try:
        val = con.sql(
            "select sector, pe as sector_pe, pbv as sector_pbv, dividend_yield as sector_dy from sectors"
            " where trade_date = (select max(trade_date) from sectors)"
        ).df()
        table = table.merge(val, on="sector", how="left")
    except duckdb.Error:
        pass
    return table
