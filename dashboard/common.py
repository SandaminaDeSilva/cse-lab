"""Shared helpers for the dashboard pages: data loading, chart styling, formatting."""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis import metrics  # noqa: E402
from collector.db import connect  # noqa: E402

DATA_DIR = ROOT / "data"

# Colours: categorical slots 1-2, diverging poles, chart chrome. Mid-tone steps
# chosen so they read on both the light and the dark Streamlit theme.
BLUE = "#3987e5"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
YELLOW = "#eda100"
SERIES = [BLUE, ORANGE, AQUA, YELLOW]
UP = "#3987e5"     # diverging pole: positive change
DOWN = "#e34948"   # diverging pole: negative change
MUTED = "#898781"
GRID = "rgba(137,135,129,0.22)"

RANGES = {"1M": 21, "3M": 63, "6M": 126, "1Y": 260}


# ------------------------------------------------------------------ data


def con():
    return connect(DATA_DIR)


@st.cache_data(ttl=900, show_spinner=False)
def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    df = con().execute(sql, list(params)).df()
    for col in df.columns:
        if col in ("trade_date", "date", "as_of", "collected_on") and len(df):
            df[col] = pd.to_datetime(df[col])
    return df


def has_table(name: str) -> bool:
    try:
        con().sql(f"select 1 from {name} limit 1")
        return True
    except Exception:  # noqa: BLE001
        return False


@st.cache_data(ttl=900, show_spinner=False)
def screener() -> pd.DataFrame:
    return metrics.screener_table(con())


@st.cache_data(ttl=900, show_spinner=False)
def stock_history(symbol: str) -> pd.DataFrame:
    return metrics.history(con(), symbol)


def status() -> dict:
    f = DATA_DIR / "status.json"
    return json.loads(f.read_text()) if f.exists() else {}


# ------------------------------------------------------------------ layout


def sidebar_status() -> None:
    s = status()
    with st.sidebar:
        if s:
            last = dt.date.fromisoformat(s["last_trade_date"])
            age = (dt.date.today() - last).days
            st.caption(f"Data up to **{last:%a %d %b %Y}**")
            # More than 4 calendar days covers a weekend plus a holiday.
            if age > 4:
                st.warning(f"Latest data is {age} days old. Check the collector in GitHub Actions.")
            if s.get("warnings"):
                with st.expander(f"{len(s['warnings'])} data warning(s)"):
                    for w in s["warnings"]:
                        st.caption(w)
        st.caption(
            "Information only. Public data from cse.lk and the Central Bank of Sri Lanka. "
            "Not investment advice; check figures with official sources before acting."
        )


def range_picker(key: str, default: str = "1Y") -> int:
    choice = st.segmented_control(
        "Range", list(RANGES), default=default, key=key, label_visibility="collapsed"
    )
    return RANGES[choice or default]


def style(fig: go.Figure, height: int = 360, legend: bool = True) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=28, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, title=None),
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", size=12),
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID, tickfont=dict(color=MUTED), automargin=True)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID, tickfont=dict(color=MUTED), automargin=True)
    return fig


# ------------------------------------------------------------------ formatting


def pct(x, digits: int = 1, sign: bool = True) -> str:
    if x is None or pd.isna(x):
        return "–"
    return f"{x * 100:+.{digits}f}%" if sign else f"{x * 100:.{digits}f}%"


def rs(x, unit: str = "auto") -> str:
    """Rupee amounts in readable units: 1,234,567,890 -> Rs 1.23 bn."""
    if x is None or pd.isna(x):
        return "–"
    a = abs(x)
    if unit == "auto":
        if a >= 1e9:
            return f"Rs {x / 1e9:,.2f} bn"
        if a >= 1e6:
            return f"Rs {x / 1e6:,.1f} mn"
        return f"Rs {x:,.0f}"
    return f"Rs {x:,.2f}"


def num(x, digits: int = 2) -> str:
    if x is None or pd.isna(x):
        return "–"
    return f"{x:,.{digits}f}"
