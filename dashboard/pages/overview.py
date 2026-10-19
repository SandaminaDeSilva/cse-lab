"""Market overview: indices, flows, breadth, sectors, movers, announcements."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common import BLUE, DOWN, ORANGE, UP, num, pct, query, range_picker, rs, screener, style

st.title("Market overview")

latest_day = query("select max(trade_date) d from prices")["d"].iloc[0]
st.caption(f"Trading day {latest_day:%A %d %B %Y}")

# ---------------------------------------------------------------- headline numbers
idx = query("select * from indices where trade_date = (select max(trade_date) from indices)").set_index("index_name")
mkt = query("select * from market order by trade_date desc limit 2")
m = mkt.iloc[0]

c1, c2, c3, c4, c5 = st.columns(5)
for col, name in ((c1, "ASPI"), (c2, "S&P SL20")):
    if name in idx.index:
        r = idx.loc[name]
        col.metric(name, num(r["value"]), f"{r['pct_change']:+.2f}%  ({r['change']:+,.2f})")
prev_turnover = mkt["turnover"].iloc[1] if len(mkt) > 1 else None
c3.metric(
    "Turnover",
    rs(m["turnover"]),
    pct(m["turnover"] / prev_turnover - 1) + " vs previous day" if prev_turnover else None,
    delta_color="off",
)
c4.metric(
    "Foreign net",
    rs(m["foreign_net"]),
    "net buying" if m["foreign_net"] >= 0 else "net selling",
    delta_color="normal" if m["foreign_net"] >= 0 else "inverse",
)
c5.metric("Advancers / decliners", f"{int(m['advancers'])} / {int(m['decliners'])}")

# ---------------------------------------------------------------- index chart
st.subheader("Indices")
n = range_picker("idx_range")
hist = query(
    "select trade_date, index_name, value from index_daily"
    " where kind = 'market' order by trade_date"
)
hist = hist.groupby("index_name").tail(n)
fig = go.Figure()
for name, color in (("ASPI", BLUE), ("S&P SL20", ORANGE)):
    g = hist[hist["index_name"] == name]
    if g.empty:
        continue
    rebased = g["value"] / g["value"].iloc[0] * 100
    fig.add_scatter(
        x=g["trade_date"], y=rebased, name=name, mode="lines", line=dict(color=color, width=2),
        customdata=g["value"], hovertemplate="%{customdata:,.2f}  (rebased %{y:.1f})<extra>" + name + "</extra>",
    )
fig.add_hline(y=100, line=dict(color="rgba(137,135,129,0.5)", width=1, dash="dot"))
st.plotly_chart(style(fig, 340), width="stretch")
st.caption("Both indices rebased to 100 at the start of the range so their moves can be compared on one scale.")

# ---------------------------------------------------------------- sectors
st.subheader("Sectors")
horizon = st.segmented_control("Sector change over", ["1D", "1M", "3M", "1Y"], default="1M", key="sec_h")
days = {"1D": 1, "1M": 21, "3M": 63, "1Y": 240}[horizon or "1M"]
sec_hist = query(
    "select trade_date, index_name as sector, value from index_daily where kind = 'sector' order by trade_date"
)
rows = []
for sector, g in sec_hist.groupby("sector"):
    v = g["value"].reset_index(drop=True)
    if len(v) > days:
        rows.append({"sector": sector, "change": v.iloc[-1] / v.iloc[-days - 1] - 1})
sec = pd.DataFrame(rows)
val = query(
    "select sector, pe, pbv, dividend_yield, turnover from sectors"
    " where trade_date = (select max(trade_date) from sectors)"
)
sec = sec.merge(val, on="sector", how="left").sort_values("change")

left, right = st.columns([3, 2])
with left:
    fig = go.Figure(
        go.Bar(
            x=sec["change"] * 100, y=sec["sector"], orientation="h",
            marker=dict(color=[UP if c >= 0 else DOWN for c in sec["change"]], cornerradius=4),
            hovertemplate="%{y}: %{x:+.1f}%<extra></extra>",
        )
    )
    fig.update_xaxes(ticksuffix="%", zeroline=True, zerolinecolor="rgba(137,135,129,0.6)")
    st.plotly_chart(style(fig, 560, legend=False).update_layout(hovermode="closest"), width="stretch")
with right:
    st.dataframe(
        sec.sort_values("pe")[["sector", "pe", "pbv", "dividend_yield", "change"]],
        hide_index=True,
        width="stretch",
        height=560,
        column_config={
            "sector": "Sector",
            "pe": st.column_config.NumberColumn("P/E", format="%.1f"),
            "pbv": st.column_config.NumberColumn("P/BV", format="%.2f"),
            "dividend_yield": st.column_config.NumberColumn("Div. yield %", format="%.1f"),
            "change": st.column_config.NumberColumn(f"{horizon} change", format="percent"),
        },
    )
st.caption("Sector P/E, P/BV and dividend yield as published by the CSE for the latest trading day.")

# ---------------------------------------------------------------- movers
st.subheader("Today's movers")
today = query(
    "select symbol, name, close, pct_change, turnover from prices"
    " where trade_date = (select max(trade_date) from prices)"
)
min_turnover = st.number_input(
    "Ignore stocks that traded less than (Rs mn) today", min_value=0.0, value=1.0, step=0.5,
    help="Thinly traded stocks can jump on a single small trade.",
)
liquid = today[today["turnover"] >= min_turnover * 1e6]
cols = {
    "symbol": "Symbol",
    "name": "Company",
    "close": st.column_config.NumberColumn("Close", format="%.2f"),
    "pct_change": st.column_config.NumberColumn("Change %", format="%+.2f"),
    "turnover": st.column_config.NumberColumn("Turnover (Rs)", format="compact"),
}
a, b, c = st.columns(3)
a.markdown("**Top gainers**")
a.dataframe(liquid.nlargest(10, "pct_change"), hide_index=True, column_config=cols, width="stretch")
b.markdown("**Top losers**")
b.dataframe(liquid.nsmallest(10, "pct_change"), hide_index=True, column_config=cols, width="stretch")
c.markdown("**Most traded**")
c.dataframe(today.nlargest(10, "turnover"), hide_index=True, column_config=cols, width="stretch")

# ---------------------------------------------------------------- announcements
st.subheader("Latest announcements")
ann = query(
    "select created_at, company, category, xd, payment_date, remarks from announcements"
    " order by created_at desc limit 40"
)
cat_filter = st.multiselect("Category", sorted(ann["category"].dropna().unique()), placeholder="All categories")
if cat_filter:
    ann = ann[ann["category"].isin(cat_filter)]
st.dataframe(
    ann, hide_index=True, width="stretch",
    column_config={
        "created_at": st.column_config.DatetimeColumn("Posted", format="DD MMM, HH:mm"),
        "company": "Company", "category": "Category", "xd": "XD date",
        "payment_date": "Payment date", "remarks": "Remarks",
    },
)

reports = query("select uploaded, company, description, pdf_url from financial_reports order by id desc limit 15")
with st.expander(f"Recent financial reports ({len(reports)})"):
    st.dataframe(
        reports, hide_index=True, width="stretch",
        column_config={
            "uploaded": "Uploaded", "company": "Company", "description": "Report",
            "pdf_url": st.column_config.LinkColumn("PDF", display_text="Open"),
        },
    )
