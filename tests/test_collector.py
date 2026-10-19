"""Tests run against a real CSE snapshot saved on 19 Oct 2026."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from collector import collect, transform, validate
from collector.db import connect

FIXTURE = Path(__file__).parent / "fixtures" / "2026-10-19"
DAY = dt.date(2026, 10, 19)


@pytest.fixture(scope="module")
def raw():
    return collect.read_raw(FIXTURE)


@pytest.fixture(scope="module")
def tables(raw):
    return collect.build_tables(raw, DAY)


def test_trade_date_is_colombo_day(raw):
    assert transform.trade_date_of(raw) == DAY


def test_prices(tables):
    p = tables["prices"]
    assert len(p) == 283
    assert not p["symbol"].duplicated().any()
    jkh = p.set_index("symbol").loc["JKH.N0000"]
    assert jkh["close"] > 0 and jkh["share_volume"] > 0
    assert {"open", "high", "low", "close", "turnover"} <= set(p.columns)


def test_indices_match_published_close(tables):
    i = tables["indices"].set_index("index_name")
    assert i.loc["ASPI", "value"] == pytest.approx(20059.42)
    assert "S&P SL20" in i.index


def test_sectors_join_valuation(tables):
    s = tables["sectors"]
    assert len(s) == 20
    banks = s.set_index("sector").loc["Banks"]
    assert banks["pe"] is not None and banks["pe"] > 0


def test_market_row(tables):
    m = tables["market"].iloc[0]
    assert m["turnover"] > 0
    assert m["foreign_net"] == pytest.approx(m["foreign_purchase"] - m["foreign_sales"])
    assert m["advancers"] == 57 and m["decliners"] == 134


def test_documents(tables):
    assert len(tables["announcements"]) > 0
    assert tables["financial_reports"]["pdf_url"].str.startswith("https://cdn.cse.lk/").all()


def test_validation_passes_on_real_day(tables):
    errors, _ = validate.check(tables)
    assert errors == []


def test_validation_catches_broken_response(tables):
    broken = dict(tables, prices=tables["prices"].head(10))
    errors, _ = validate.check(broken)
    assert any("prices" in e for e in errors)


def test_store_and_query_roundtrip(tmp_path, raw, tables):
    for name, df in tables.items():
        collect.write_table(df, collect.table_path(tmp_path, name, DAY))
    for name, payload in raw.items():
        collect.write_raw(collect.raw_dir(tmp_path, DAY), name, payload)
    con = connect(tmp_path)
    n = con.sql("select count(*) from prices").fetchone()[0]
    assert n == 283
    aspi = con.sql("select value from indices where index_name = 'ASPI'").fetchone()[0]
    assert aspi == pytest.approx(20059.42)
    # Rebuilding from the raw archive reproduces the same tables.
    collect.rebuild(tmp_path)
    assert connect(tmp_path).sql("select count(*) from prices").fetchone()[0] == 283
