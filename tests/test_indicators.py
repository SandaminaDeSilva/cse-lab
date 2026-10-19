import numpy as np
import pandas as pd
import pytest

from analysis import indicators as ind


@pytest.fixture
def prices():
    rng = np.random.default_rng(7)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))))
    return pd.DataFrame({"close": close, "high": close * 1.01, "low": close * 0.99})


def test_sma_matches_manual():
    s = pd.Series([1.0, 2, 3, 4, 5])
    assert ind.sma(s, 3).tolist()[2:] == [2.0, 3.0, 4.0]


def test_rsi_bounds_and_extremes(prices):
    r = ind.rsi(prices["close"]).dropna()
    assert r.between(0, 100).all()
    rising = pd.Series(np.arange(1.0, 40.0))
    assert ind.rsi(rising).iloc[-1] == pytest.approx(100.0)
    falling = pd.Series(np.arange(40.0, 1.0, -1))
    assert ind.rsi(falling).iloc[-1] == pytest.approx(0.0)


def test_rsi_wilder_reference():
    # Widely used worked example (StockCharts): first 14-day RSI 70.53, then 66.32.
    # Their sheet rounds intermediate averages to 2 decimals, so allow 0.1.
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
              45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64]
    r = ind.rsi(pd.Series(closes), 14).dropna()
    assert r.iloc[0] == pytest.approx(70.53, abs=0.1)
    assert r.iloc[1] == pytest.approx(66.32, abs=0.1)


def test_bollinger_contains_middle(prices):
    bb = ind.bollinger(prices["close"]).dropna()
    assert (bb["lower"] <= bb["middle"]).all() and (bb["middle"] <= bb["upper"]).all()


def test_atr_positive(prices):
    a = ind.atr(prices).dropna()
    assert (a > 0).all()


def test_returns_and_drawdown():
    s = pd.Series([100.0, 110, 99, 120])
    assert ind.pct_return(s, 1) == pytest.approx(120 / 99 - 1)
    assert ind.pct_return(s, 10) is None
    assert ind.max_drawdown(s) == pytest.approx(99 / 110 - 1)


def test_add_all_columns(prices):
    out = ind.add_all(prices)
    for col in ["sma_20", "sma_50", "sma_200", "rsi_14", "macd", "signal", "bb_upper", "atr_14"]:
        assert col in out
