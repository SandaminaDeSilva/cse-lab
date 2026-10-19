"""Single-stock page: price, trend, momentum, volume, key numbers, company news."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from common import BLUE, MUTED, ORANGE, YELLOW, AQUA, GRID, num, pct, query, range_picker, rs, screener, stock_history, style
from analysis import indicators as ind

table = screener().sort_values("avg_turnover_20d", ascending=False)
labels = {r.symbol: f"{r.symbol.split('.')[0]} · {r.name}" if isinstance(r.name, str) else r.symbol
          for r in table.itertuples()}
options = list(labels)
default = st.query_params.get("symbol", "JKH.N0000")
symbol = st.selectbox(
    "Stock", options, index=options.index(default) if default in options else 0,
    format_func=lambda s: labels[s], help="Sorted by recent turnover; type to search.",
)
st.query_params["symbol"] = symbol
row = table.set_index("symbol").loc[symbol]

st.title(labels[symbol])
meta = [x for x in (row.get("sector"), f"Beta vs ASPI {row['beta_aspi']:.2f}" if pd.notna(row.get("beta_aspi")) else None) if x]
if meta:
    st.caption(" · ".join(meta))

# ---------------------------------------------------------------- key numbers
c = st.columns(6)
c[0].metric("Close", num(row["close"]), pct(row["chg_1d"], 2))
c[1].metric("1 month", pct(row["ret_1m"]))
c[2].metric("3 months", pct(row["ret_3m"]))
c[3].metric("12 months", pct(row["ret_12m"]))
c[4].metric("From 52-week high", pct(row["from_52w_high"]), help=f"52-week range {num(row['low_52w'])} – {num(row['high_52w'])}")
c[5].metric("RSI (14)", num(row["rsi_14"], 0), help="Above 70 is often read as overbought, below 30 as oversold.")
c = st.columns(6)
c[0].metric("Market cap", rs(row["market_cap"]))
c[1].metric("Avg daily turnover (20d)", rs(row["avg_turnover_20d"]))
c[2].metric("Volatility (60d, yearly)", pct(row["volatility_60d"], 0, sign=False))
c[3].metric("vs 50-day average", pct(row["vs_sma_50"]))
c[4].metric("vs 200-day average", pct(row["vs_sma_200"]))
c[5].metric("Sector P/E", num(row.get("sector_pe"), 1), help="The CSE publishes P/E per sector, not per stock.")

# ---------------------------------------------------------------- chart
hist = ind.add_all(stock_history(symbol))
n = range_picker("stock_range")
view = hist.tail(n)

opts = st.pills(
    "Overlays", ["20-day avg", "50-day avg", "200-day avg", "Bollinger bands"],
    selection_mode="multi", default=["50-day avg", "200-day avg"], key="overlays",
)
fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.6, 0.15, 0.25])
if "Bollinger bands" in opts:
    fig.add_scatter(x=view["trade_date"], y=view["bb_upper"], line=dict(width=0), showlegend=False,
                    hoverinfo="skip", row=1, col=1)
    fig.add_scatter(x=view["trade_date"], y=view["bb_lower"], line=dict(width=0), fill="tonexty",
                    fillcolor="rgba(57,135,229,0.10)", name="Bollinger (20, 2)", hoverinfo="skip", row=1, col=1)
fig.add_scatter(x=view["trade_date"], y=view["close"], name="Close", line=dict(color=BLUE, width=2),
                hovertemplate="%{y:,.2f}", row=1, col=1)
for label, colname, color in (("20-day avg", "sma_20", AQUA), ("50-day avg", "sma_50", ORANGE), ("200-day avg", "sma_200", YELLOW)):
    if label in opts:
        fig.add_scatter(x=view["trade_date"], y=view[colname], name=label, line=dict(color=color, width=1.5),
                        hovertemplate="%{y:,.2f}", row=1, col=1)
fig.add_bar(x=view["trade_date"], y=view["share_volume"], name="Volume", marker=dict(color=MUTED),
            showlegend=False, hovertemplate="%{y:,.0f} shares", row=2, col=1)
fig.add_scatter(x=view["trade_date"], y=view["rsi_14"], name="RSI (14)", line=dict(color=BLUE, width=1.5),
                showlegend=False, hovertemplate="RSI %{y:.0f}", row=3, col=1)
for level in (30, 70):
    fig.add_hline(y=level, line=dict(color="rgba(137,135,129,0.6)", width=1, dash="dot"), row=3, col=1)
fig.update_yaxes(title_text="Price (Rs)", row=1, col=1)
fig.update_yaxes(title_text="Volume", row=2, col=1)
fig.update_yaxes(title_text="RSI", range=[0, 100], tickvals=[30, 50, 70], row=3, col=1)
st.plotly_chart(style(fig, 620), width="stretch")

with st.expander("MACD (12, 26, 9)"):
    f2 = go.Figure()
    f2.add_bar(x=view["trade_date"], y=view["histogram"], name="Histogram",
               marker=dict(color=["rgba(57,135,229,0.55)" if v >= 0 else "rgba(227,73,72,0.55)" for v in view["histogram"].fillna(0)]))
    f2.add_scatter(x=view["trade_date"], y=view["macd"], name="MACD", line=dict(color=BLUE, width=1.5))
    f2.add_scatter(x=view["trade_date"], y=view["signal"], name="Signal", line=dict(color=ORANGE, width=1.5))
    st.plotly_chart(style(f2, 260), width="stretch")
    st.caption("MACD crossing above its signal line is a common bullish momentum signal; crossing below, bearish.")

backfill_days = int((view["source"] == "backfill").sum())
if backfill_days:
    st.caption(
        f"{backfill_days} of these days come from the CSE's one-year chart history, which has close, high, low "
        "and volume but no opening price; turnover for those days is estimated as close × volume."
    )

# ---------------------------------------------------------------- company info and news
comp = query(
    "select business, website, established, board from companies where symbol = ?"
    " order by as_of desc limit 1", (symbol,)
)
if not comp.empty and comp["business"].notna().iloc[0]:
    with st.expander("About the company"):
        r = comp.iloc[0]
        st.write(r["business"])
        st.caption(" · ".join(str(x) for x in (r["board"], f"est. {r['established']}" if r["established"] else None, r["website"]) if x))

name = row["name"] if isinstance(row["name"], str) else ""
ticker = symbol.split(".")[0]
ann = query(
    "select created_at, category, xd, payment_date, remarks from announcements where company = ? order by created_at desc",
    (name,),
)
rep = query(
    "select uploaded, description, pdf_url from financial_reports where symbol = ? order by id desc", (ticker,)
)
st.subheader("Announcements and reports")
if ann.empty and rep.empty:
    st.caption("None collected yet for this company. New ones appear here as the daily collector picks them up.")
if not ann.empty:
    st.dataframe(ann, hide_index=True, width="stretch", column_config={
        "created_at": st.column_config.DatetimeColumn("Posted", format="DD MMM YYYY"),
        "category": "Category", "xd": "XD date", "payment_date": "Payment date", "remarks": "Remarks"})
if not rep.empty:
    st.dataframe(rep, hide_index=True, width="stretch", column_config={
        "uploaded": "Uploaded", "description": "Report",
        "pdf_url": st.column_config.LinkColumn("PDF", display_text="Open")})
