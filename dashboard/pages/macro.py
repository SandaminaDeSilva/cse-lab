"""Macro panel: Central Bank rates, T-bills, rupee, inflation, oil, against the ASPI."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common import AQUA, BLUE, ORANGE, YELLOW, has_table, num, query, style

st.title("Macro")
st.caption(
    "From the Central Bank of Sri Lanka's Daily Economic Indicators report. "
    "Interest rates and the rupee drive the CSE more than most single-company news."
)

if not has_table("macro"):
    st.info("No macro data yet.")
    st.stop()

m = query("select * from macro order by date")
aspi = query("select trade_date as date, value from index_daily where index_name = 'ASPI' order by trade_date")
start = m["date"].min()
aspi = aspi[aspi["date"] >= start]


def last(col: str):
    s = m[["date", col]].dropna()
    return s.iloc[-1] if len(s) else None


def delta(col: str, days: int = 91, unit: str = " pts"):
    s = m[["date", col]].dropna()
    if len(s) < 2:
        return None
    now = s.iloc[-1]
    past = s[s["date"] <= now["date"] - pd.Timedelta(days=days)]
    if past.empty:
        return None
    return f"{now[col] - past.iloc[-1][col]:+.2f}{unit} in 3 months"


cols = st.columns(5)
tiles = [
    ("Policy rate (OPR)", "opr", "%"),
    ("12-month T-bill", "tbill_364d", "%"),
    ("USD/LKR (indicative)", "usd_spot", ""),
    ("Inflation (CCPI, y/y)", "ccpi_yoy", "%"),
    ("Brent oil (USD/bbl)", "brent", ""),
]
for col, (label, key, suffix) in zip(cols, tiles):
    r = last(key)
    if r is not None:
        col.metric(label, f"{num(r[key])}{suffix}", delta(key, unit=" pts" if suffix == "%" else ""),
                   delta_color="off", help=f"As of {r['date']:%d %b %Y}")


def line_chart(series: list[tuple[str, str, str]], title: str, suffix: str = "", height: int = 300):
    fig = go.Figure()
    for label, col, color in series:
        s = m[["date", col]].dropna()
        fig.add_scatter(x=s["date"], y=s[col], name=label, mode="lines", line=dict(color=color, width=2, shape="hv" if col == "opr" else "linear"),
                        hovertemplate="%{y:.2f}" + suffix)
    st.markdown(f"**{title}**")
    if suffix:
        fig.update_yaxes(ticksuffix=suffix)
    return style(fig, height, legend=len(series) > 1)


left, right = st.columns(2)
with left:
    st.plotly_chart(line_chart(
        [("Policy rate", "opr", BLUE), ("91-day", "tbill_91d", ORANGE), ("182-day", "tbill_182d", AQUA), ("364-day", "tbill_364d", YELLOW)],
        "Policy rate and T-bill auction yields", "%"), width="stretch")
with right:
    fig = go.Figure(go.Scatter(x=aspi["date"], y=aspi["value"], mode="lines", line=dict(color=BLUE, width=2),
                               name="ASPI", hovertemplate="%{y:,.0f}"))
    st.markdown("**ASPI over the same period**")
    st.plotly_chart(style(fig, 300, legend=False), width="stretch")

left, right = st.columns(2)
with left:
    st.plotly_chart(line_chart([("USD/LKR", "usd_spot", BLUE)], "Rupees per US dollar (indicative spot)"), width="stretch")
with right:
    # Inflation is monthly; plot each published month once.
    infl = []
    for label, mcol, vcol, color in (("CCPI (Colombo)", "ccpi_month", "ccpi_yoy", BLUE), ("NCPI (national)", "ncpi_month", "ncpi_yoy", ORANGE)):
        if mcol in m:
            s = m[[mcol, vcol]].dropna().drop_duplicates(mcol, keep="last").sort_values(mcol)
            infl.append((label, s, mcol, vcol, color))
    fig = go.Figure()
    for label, s, mcol, vcol, color in infl:
        fig.add_scatter(x=s[mcol], y=s[vcol], name=label, mode="lines+markers", line=dict(color=color, width=2),
                        marker=dict(size=8), hovertemplate="%{y:.1f}%")
    st.markdown("**Inflation, year on year**")
    fig.update_yaxes(ticksuffix="%")
    st.plotly_chart(style(fig, 300), width="stretch")

left, right = st.columns(2)
with left:
    # Real yield: what a 12-month T-bill pays after inflation. When it is high,
    # cash is a strong competitor to shares.
    tb = m[["date", "tbill_364d"]].dropna()
    cp = m[["date", "ccpi_yoy"]].dropna()
    real = pd.merge_asof(tb.sort_values("date"), cp.sort_values("date"), on="date").dropna()
    real["real"] = real["tbill_364d"] - real["ccpi_yoy"]
    fig = go.Figure(go.Scatter(x=real["date"], y=real["real"], mode="lines", line=dict(color=BLUE, width=2),
                               name="Real yield", hovertemplate="%{y:.2f}%"))
    fig.add_hline(y=0, line=dict(color="rgba(137,135,129,0.6)", width=1, dash="dot"))
    st.markdown("**Real 12-month T-bill yield** (minus CCPI inflation)")
    fig.update_yaxes(ticksuffix="%")
    st.plotly_chart(style(fig, 300, legend=False), width="stretch")
with right:
    st.plotly_chart(line_chart([("Brent", "brent", BLUE), ("WTI", "wti", ORANGE)], "Crude oil (USD per barrel)"), width="stretch")

st.caption(
    "T-bill yields are the latest primary auction results. Inflation figures are monthly and appear with a lag. "
    "Values the parser could not read reliably are left blank rather than guessed."
)
