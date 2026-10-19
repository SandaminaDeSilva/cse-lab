"""Standard technical indicators, written out in plain pandas.

Every function takes a price series (or a DataFrame with high/low/close)
sorted oldest first and returns values aligned to the same index.
Definitions follow the usual textbook versions (RSI and ATR use Wilder's
smoothing), so the numbers match common charting tools.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 242  # roughly a CSE trading year


def sma(close: pd.Series, n: int) -> pd.Series:
    return close.rolling(n, min_periods=n).mean()


def ema(close: pd.Series, n: int) -> pd.Series:
    return close.ewm(span=n, adjust=False, min_periods=n).mean()


def wilder(values: pd.Series, n: int) -> pd.Series:
    """Wilder's smoothing: the first value is a simple average of n values,
    then each step is prev + (x - prev) / n. Leading NaNs are skipped."""
    x = values.to_numpy(dtype=float)
    out = np.full(len(x), np.nan)
    valid = np.flatnonzero(~np.isnan(x))
    if len(valid) < n:
        return pd.Series(out, index=values.index)
    start = valid[0]
    seed_end = start + n
    if np.isnan(x[start:seed_end]).any():
        return pd.Series(out, index=values.index)
    prev = x[start:seed_end].mean()
    out[seed_end - 1] = prev
    for i in range(seed_end, len(x)):
        if not np.isnan(x[i]):
            prev = prev + (x[i] - prev) / n
        out[i] = prev
    return pd.Series(out, index=values.index)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Relative Strength Index, 0-100. Above 70 is often read as overbought, below 30 oversold."""
    delta = close.diff()
    avg_gain = wilder(delta.clip(lower=0), n)
    avg_loss = wilder(-delta.clip(upper=0), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100 - 100 / (1 + avg_gain / avg_loss)
    # No losses at all in the window means RSI is 100.
    return out.where(avg_loss != 0, 100.0).where(avg_gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "histogram": line - sig})


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    return pd.DataFrame({"middle": mid, "upper": mid + k * sd, "lower": mid - k * sd})


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average True Range: typical daily price movement, in rupees."""
    prev_close = df["close"].shift()
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    return wilder(tr, n)


def pct_return(close: pd.Series, n: int) -> float | None:
    """Return over the last n trading days, as a fraction (0.05 = +5%)."""
    if len(close) <= n:
        return None
    start = close.iloc[-n - 1]
    return None if not start else close.iloc[-1] / start - 1


def volatility(close: pd.Series, n: int = 60) -> float | None:
    """Annualised volatility of daily returns over the last n days."""
    r = close.pct_change().dropna().tail(n)
    if len(r) < max(10, n // 2):
        return None
    return float(r.std(ddof=1) * np.sqrt(TRADING_DAYS))


def max_drawdown(close: pd.Series) -> float | None:
    """Largest peak-to-trough fall over the series, as a negative fraction."""
    if close.empty:
        return None
    peak = close.cummax()
    return float((close / peak - 1).min())


def add_all(df: pd.DataFrame) -> pd.DataFrame:
    """Add the standard indicator columns to one stock's daily table."""
    out = df.copy()
    c = out["close"]
    for n in (20, 50, 200):
        out[f"sma_{n}"] = sma(c, n)
    out["ema_20"] = ema(c, 20)
    out["rsi_14"] = rsi(c, 14)
    out = out.join(macd(c))
    bb = bollinger(c)
    out["bb_upper"], out["bb_middle"], out["bb_lower"] = bb["upper"], bb["middle"], bb["lower"]
    out["atr_14"] = atr(out, 14)
    return out
