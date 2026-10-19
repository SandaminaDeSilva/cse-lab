"""Turn raw CSE API responses into tidy tables.

Each function takes the raw JSON exactly as the API returned it and the
trade date the snapshot belongs to, and returns a pandas DataFrame.
Field names are renamed to plain snake_case; nothing is dropped silently.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

COLOMBO = dt.timezone(dt.timedelta(hours=5, minutes=30))
CDN = "https://cdn.cse.lk/"


def ms_to_date(ms: float | int | None) -> dt.date | None:
    """CSE timestamps are epoch milliseconds; trade dates are Colombo midnight."""
    if ms is None:
        return None
    return dt.datetime.fromtimestamp(ms / 1000, COLOMBO).date()


def ms_to_ts(ms: float | int | None) -> pd.Timestamp | None:
    if ms is None:
        return None
    return pd.Timestamp(dt.datetime.fromtimestamp(ms / 1000, COLOMBO))


def _flatten(value: Any) -> list[dict]:
    """Some endpoints wrap their rows in one or two extra list levels."""
    rows: list[dict] = []
    if isinstance(value, dict):
        rows.append(value)
    elif isinstance(value, list):
        for item in value:
            rows.extend(_flatten(item))
    return rows


def trade_date_of(raw: dict[str, Any]) -> dt.date:
    """The trading day a snapshot describes, taken from the market's own data.

    On a weekend or holiday the API still shows the last trading day, so this
    is how the collector knows there is nothing new to save.
    """
    gics = raw.get("GICSSectorSummery") or {}
    if isinstance(gics, dict) and gics.get("reqTradeDate"):
        return ms_to_date(gics["reqTradeDate"])
    daily = _flatten(raw.get("dailyMarketSummery"))
    if daily:
        return max(ms_to_date(r["tradeDate"]) for r in daily if r.get("tradeDate"))
    summary = raw.get("marketSummery") or {}
    if summary.get("tradeDate"):
        return ms_to_date(summary["tradeDate"])
    raise ValueError("could not determine the trade date from the snapshot")


def prices(raw: dict[str, Any], trade_date: dt.date) -> pd.DataFrame:
    rows = (raw.get("tradeSummary") or {}).get("reqTradeSummery") or []
    out = []
    for r in rows:
        out.append(
            {
                "trade_date": trade_date,
                "symbol": r.get("symbol"),
                "name": r.get("name"),
                "security_id": r.get("id"),
                "open": r.get("open"),
                "high": r.get("high"),
                "low": r.get("low"),
                "close": r.get("closingPrice"),
                "last_price": r.get("price"),
                "previous_close": r.get("previousClose"),
                "change": r.get("change"),
                "pct_change": r.get("percentageChange"),
                "share_volume": r.get("sharevolume"),
                "trades": r.get("tradevolume"),
                "turnover": r.get("turnover"),
                "crossing_volume": r.get("crossingVolume"),
                "crossing_trades": r.get("crossingTradeVol"),
                "market_cap": r.get("marketCap"),
                "last_traded_at": ms_to_ts(r.get("lastTradedTime")),
                "status": r.get("status"),
                "issue_date": r.get("issueDate"),
            }
        )
    return pd.DataFrame(out)


def indices(raw: dict[str, Any], trade_date: dt.date) -> pd.DataFrame:
    out = []
    for key, name in (("aspiData", "ASPI"), ("snpData", "S&P SL20")):
        r = raw.get(key)
        if not r:
            continue
        out.append(
            {
                "trade_date": trade_date,
                "index_name": name,
                "value": r.get("value"),
                "high": r.get("highValue"),
                "low": r.get("lowValue"),
                "change": r.get("change"),
                "pct_change": r.get("percentage"),
                "as_of": ms_to_ts(r.get("timestamp")),
            }
        )
    return pd.DataFrame(out)


def sectors(raw: dict[str, Any], trade_date: dt.date) -> pd.DataFrame:
    """Sector index levels joined with sector valuation (P/E, P/BV, yield)."""
    levels = _flatten(raw.get("marketIndices"))
    gics = (raw.get("GICSSectorSummery") or {}).get("reqGICSSectorSummery") or []
    valuation = {g.get("sectorId"): g for g in gics}
    out = []
    for r in levels:
        code = r.get("indexCodeSp")
        v = valuation.get(code, {})
        out.append(
            {
                "trade_date": trade_date,
                "sector": r.get("name"),
                "sector_symbol": r.get("symbol"),
                "index_code": code,
                "index_value": r.get("indexValue"),
                "previous_close": r.get("sectorPreviousClose"),
                "change": r.get("change"),
                "pct_change": r.get("percentage"),
                "turnover": r.get("sectorTurnoverToday"),
                "share_volume": r.get("sectorVolumeToday"),
                "trades": r.get("sectorTradeToday"),
                "pe": _num(v.get("per")),
                "pbv": _num(v.get("pbv")),
                "dividend_yield": _num(v.get("dy")),
                "companies_traded": v.get("companiesTraded"),
                "companies_listed": v.get("companiesListed"),
            }
        )
    return pd.DataFrame(out)


def market(raw: dict[str, Any], trade_date: dt.date) -> pd.DataFrame:
    """One row per day: turnover, domestic vs foreign flows, breadth."""
    daily = [r for r in _flatten(raw.get("dailyMarketSummery")) if ms_to_date(r.get("tradeDate")) == trade_date]
    d = daily[0] if daily else {}
    summary = raw.get("marketSummery") or {}
    breadth = raw.get("getContributors") or {}
    fp, fs = d.get("equityForeignPurchase"), d.get("equityForeignSales")
    row = {
        "trade_date": trade_date,
        "turnover": d.get("equityTurnover", summary.get("tradeVolume")),
        "trades": d.get("tradesNo", summary.get("trades")),
        "share_volume": d.get("volumeOfTurnOverNumber", summary.get("shareVolume")),
        "domestic_purchase": d.get("equityDomesticPurchase"),
        "domestic_sales": d.get("equityDomesticSales"),
        "foreign_purchase": fp,
        "foreign_sales": fs,
        "foreign_net": (fp - fs) if fp is not None and fs is not None else None,
        "market_cap": d.get("marketCap"),
        "listed_companies": d.get("listedCompanyNumber"),
        "traded_companies": d.get("tradeCompanyNumber"),
        "advancers": breadth.get("reqPositiveCount"),
        "decliners": breadth.get("reqNegativeCount"),
    }
    return pd.DataFrame([row])


def announcements(raw: dict[str, Any], trade_date: dt.date) -> pd.DataFrame:
    rows = (raw.get("approvedAnnouncement") or {}).get("approvedAnnouncements") or []
    out = []
    for r in rows:
        out.append(
            {
                "collected_on": trade_date,
                "id": r.get("id"),
                "announcement_id": r.get("announcementId"),
                "announced": r.get("dateOfAnnouncement"),
                "created_at": ms_to_ts(r.get("createdDate")),
                "category": r.get("announcementCategory"),
                "company": r.get("company"),
                "symbol": r.get("symbol"),
                "type": r.get("type"),
                "record_date": r.get("recordDate"),
                "xd": r.get("xd"),
                "xr": r.get("xr"),
                "payment_date": r.get("paymentDate"),
                "agm_date": r.get("agmDate"),
                "remarks": r.get("remarks"),
            }
        )
    return pd.DataFrame(out)


def financial_reports(raw: dict[str, Any], trade_date: dt.date) -> pd.DataFrame:
    rows = (raw.get("getFinancialAnnouncement") or {}).get("reqFinancialAnnouncemnets") or []
    out = []
    for r in rows:
        path = r.get("path")
        out.append(
            {
                "collected_on": trade_date,
                "id": r.get("id"),
                "company": r.get("name"),
                "symbol": r.get("symbol"),
                "description": r.get("fileText"),
                "uploaded": r.get("uploadedDate"),
                "period_date": ms_to_date(r.get("manualDate")),
                "pdf_url": CDN + path if path else None,
            }
        )
    return pd.DataFrame(out)


def companies(
    company_raw: dict[str, Any], as_of: dt.date, profiles: dict[str, Any] | None = None
) -> pd.DataFrame:
    """Weekly per-company snapshot: sector, size, ranges, foreign holding, beta."""
    profiles = profiles or {}
    out = []
    for symbol, resp in company_raw.items():
        info = (resp or {}).get("reqSymbolInfo") or {}
        beta = (resp or {}).get("reqSymbolBetaInfo") or {}
        if not info:
            continue
        prof = profiles.get(symbol) or {}
        summary = (prof.get("reqComSumInfo") or [{}])[0] or {}
        business = (prof.get("infoCompanyBusinessSummary") or [{}])[0] or {}
        out.append(
            {
                "as_of": as_of,
                "symbol": symbol,
                "name": info.get("name"),
                "sector": normalize_sector(summary.get("sector")),
                "sector_raw": summary.get("sector"),
                "board": summary.get("boardType"),
                "established": summary.get("established"),
                "website": summary.get("web"),
                "business": (business.get("body") or "").strip() or None,
                "isin": info.get("isin"),
                "shares_issued": info.get("quantityIssued"),
                "par_value": info.get("parValue"),
                "market_cap": info.get("marketCap"),
                "foreign_holdings": info.get("foreignHoldings"),
                "foreign_pct": info.get("foreignPercentage"),
                "high_52w": info.get("p12HiPrice"),
                "low_52w": info.get("p12LowPrice"),
                "high_ytd": info.get("ytdHiPrice"),
                "low_ytd": info.get("ytdLowPrice"),
                "high_all_time": info.get("allHiPrice"),
                "low_all_time": info.get("allLowPrice"),
                "turnover_mtd": info.get("mtdTurnover"),
                "turnover_ytd": info.get("ytdTurnover"),
                "share_volume_12m": info.get("p12ShareVolume"),
                "beta_aspi": beta.get("triASIBetaValue"),
                "beta_spsl20": beta.get("betaValueSPSL"),
                "beta_period": f"{beta.get('triASIBetaPeriod')} Q{beta.get('quarter')}" if beta else None,
            }
        )
    return pd.DataFrame(out)


# Company profiles give the sector as free text ("Banks ", "FOOD BEVERAGE & TOBACCO",
# "Materials (1510)", sub-industry names...). Map them onto the 20 sector-index
# names so stocks join with sector P/E and sector index levels.
GICS_SECTORS = [
    "Automobiles & Components", "Banks", "Capital Goods", "Commercial & Professional Services",
    "Consumer Durables & Apparel", "Consumer Services", "Diversified Financials", "Energy",
    "Food & Staples Retailing", "Food, Beverage & Tobacco", "Health Care Equipment & Services",
    "Household & Personal Products", "Insurance", "Materials", "Real Estate Management&Development",
    "Retailing", "Software & Services", "Telecommunication Services", "Transportation", "Utilities",
]
_SECTOR_ALIASES = {
    "diversifiedfinancial": "Diversified Financials",
    "diversifiedfinancialservices": "Diversified Financials",
    "investmentbankingbrokerage": "Diversified Financials",
    "consumerfinance": "Diversified Financials",
    "banksfinanceinsurance": "Diversified Financials",
    "propertycasualtyinsurance": "Insurance",
    "multilineinsurance": "Insurance",
    "applicationsoftware": "Software & Services",
    "independentpowerproducersenergytraders": "Utilities",
    "powerenergy": "Utilities",
    "industrials": "Capital Goods",
    "realestate": "Real Estate Management&Development",
    "realestatedevelopment": "Real Estate Management&Development",
}


def _sector_key(text: str) -> str:
    import re

    t = re.sub(r"\(.*?\)|\d+", " ", text.lower()).replace(" and ", " ")
    return re.sub(r"[^a-z]", "", t)


_SECTOR_LOOKUP = {_sector_key(s): s for s in GICS_SECTORS} | _SECTOR_ALIASES


def normalize_sector(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    return _SECTOR_LOOKUP.get(_sector_key(raw), raw.strip())


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Table name -> builder for the daily snapshot.
DAILY_TABLES = {
    "prices": prices,
    "indices": indices,
    "sectors": sectors,
    "market": market,
    "announcements": announcements,
    "financial_reports": financial_reports,
}
