"""CSE Lab dashboard.

Run locally:   streamlit run dashboard/app.py
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="CSE Lab", page_icon="📈", layout="wide")

from common import DATA_DIR, sidebar_status  # noqa: E402

if not (DATA_DIR / "parquet" / "prices").exists():
    st.title("CSE Lab")
    st.info("No data yet. The collector saves the first snapshot after the next market close.")
    st.stop()

pages = st.navigation(
    [
        st.Page("pages/overview.py", title="Market overview", icon="🏛️", default=True),
        st.Page("pages/stock.py", title="Stock", icon="📈"),
        st.Page("pages/screener.py", title="Screener", icon="🔎"),
        st.Page("pages/macro.py", title="Macro", icon="🏦"),
    ]
)
sidebar_status()
pages.run()
