"""Screener: filter all stocks by liquidity, trend, momentum and sector valuation."""

from __future__ import annotations

import streamlit as st

from common import screener

st.title("Screener")
st.caption("Filter every listed stock, then click a column header to sort. Returns use daily closes.")

df = screener()

with st.container(border=True):
    a, b, c, d = st.columns(4)
    sectors = a.multiselect("Sector", sorted(df["sector"].dropna().unique()), placeholder="All sectors")
    min_turn = b.number_input(
        "Min. avg daily turnover (Rs mn)", min_value=0.0, value=1.0, step=0.5,
        help="20-day average. Low-turnover stocks can be hard to buy or sell at the quoted price.",
    )
    rsi_lo, rsi_hi = c.slider("RSI (14) range", 0, 100, (0, 100))
    trend = d.selectbox("Trend", ["Any", "Above 200-day average", "Below 200-day average", "Above 50-day average"])
    e, f, g, h = st.columns(4)
    ret_3m = e.number_input("Min. 3-month return (%)", value=-100.0, step=5.0)
    max_pe = f.number_input("Max. sector P/E", value=0.0, step=1.0, help="0 means no limit.")
    min_mcap = g.number_input("Min. market cap (Rs bn)", min_value=0.0, value=0.0, step=1.0)
    min_days = h.number_input("Min. days of history", min_value=0, value=60, step=10,
                              help="Stocks with little history give unreliable averages and RSI.")

f_ = df.copy()
if sectors:
    f_ = f_[f_["sector"].isin(sectors)]
f_ = f_[f_["avg_turnover_20d"].fillna(0) >= min_turn * 1e6]
f_ = f_[f_["rsi_14"].between(rsi_lo, rsi_hi) | ((rsi_lo == 0) & (rsi_hi == 100))]
if trend == "Above 200-day average":
    f_ = f_[f_["vs_sma_200"] > 0]
elif trend == "Below 200-day average":
    f_ = f_[f_["vs_sma_200"] < 0]
elif trend == "Above 50-day average":
    f_ = f_[f_["vs_sma_50"] > 0]
f_ = f_[(f_["ret_3m"].fillna(-9) * 100 >= ret_3m) | (ret_3m <= -100)]
if max_pe > 0:
    f_ = f_[f_["sector_pe"] <= max_pe]
f_ = f_[f_["market_cap"].fillna(0) >= min_mcap * 1e9]
f_ = f_[f_["days_of_history"] >= min_days]

st.markdown(f"**{len(f_)}** of {len(df)} stocks match")

cols = ["symbol", "name", "sector", "close", "chg_1d", "ret_1m", "ret_3m", "ret_12m", "rsi_14",
        "vs_sma_200", "from_52w_high", "volatility_60d", "avg_turnover_20d", "market_cap", "beta_aspi",
        "sector_pe", "sector_dy"]
view = f_[cols].sort_values("avg_turnover_20d", ascending=False)
pc = lambda label: st.column_config.NumberColumn(label, format="percent")  # noqa: E731
st.dataframe(
    view, hide_index=True, width="stretch", height=620,
    column_config={
        "symbol": st.column_config.TextColumn("Symbol", pinned=True),
        "name": "Company", "sector": "Sector",
        "close": st.column_config.NumberColumn("Close", format="%.2f"),
        "chg_1d": pc("1D"), "ret_1m": pc("1M"), "ret_3m": pc("3M"), "ret_12m": pc("12M"),
        "rsi_14": st.column_config.NumberColumn("RSI", format="%.0f"),
        "vs_sma_200": pc("vs 200d avg"), "from_52w_high": pc("From 52w high"),
        "volatility_60d": pc("Volatility"),
        "avg_turnover_20d": st.column_config.NumberColumn("Avg turnover (Rs)", format="compact"),
        "market_cap": st.column_config.NumberColumn("Market cap (Rs)", format="compact"),
        "beta_aspi": st.column_config.NumberColumn("Beta", format="%.2f"),
        "sector_pe": st.column_config.NumberColumn("Sector P/E", format="%.1f"),
        "sector_dy": st.column_config.NumberColumn("Sector yield %", format="%.1f"),
    },
)
st.download_button("Download as CSV", view.to_csv(index=False), "cse_screener.csv", "text/csv")
st.caption(
    "To open a stock's page, go to **Stock** and type its symbol. P/E and dividend yield are sector "
    "figures published by the CSE; per-company valuation needs the quarterly reports (Phase 3)."
)
