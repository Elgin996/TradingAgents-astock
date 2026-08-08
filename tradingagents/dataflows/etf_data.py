"""Phase-1 ETF data adapters with auditable field metadata."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from io import StringIO
from typing import Any

import pandas as pd

from .a_stock import _em_get, _tencent_quote
from .instrument import DataPoint
from .security_master import resolve_fund_master

_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://fund.eastmoney.com/",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _render(points: dict[str, DataPoint]) -> str:
    return json.dumps(
        {key: point.to_dict() for key, point in points.items()},
        ensure_ascii=False,
        indent=2,
    )


def get_etf_profile(symbol: str) -> str:
    """Return validated fund identity fields from the phase-0 security master."""
    retrieved_at = _now()
    try:
        record = resolve_fund_master(symbol)
        return _render(
            {
                "fund_name": DataPoint(record.fund_name, None, None, retrieved_at, "Eastmoney FundF10", "ok"),
                "tracking_index_name": DataPoint(record.tracking_index_name, None, None, retrieved_at, "Eastmoney FundF10", "ok" if record.tracking_index_name else "missing"),
                "fund_manager": DataPoint(record.fund_manager, None, None, retrieved_at, "Eastmoney FundF10", "ok" if record.fund_manager else "missing"),
                "management_fee": DataPoint(record.management_fee, "%", None, retrieved_at, "Eastmoney FundF10", "ok" if record.management_fee else "missing"),
                "custodian_fee": DataPoint(record.custodian_fee, "%", None, retrieved_at, "Eastmoney FundF10", "ok" if record.custodian_fee else "missing"),
            }
        )
    except Exception as exc:
        return _render({"profile": DataPoint(None, None, None, retrieved_at, "Eastmoney FundF10", "error", str(exc))})


def get_etf_quote(symbol: str) -> str:
    """Return a Tencent ETF quote snapshot, including turnover when published."""
    retrieved_at = _now()
    try:
        quote = _tencent_quote([symbol]).get(symbol)
        if not quote:
            raise RuntimeError("腾讯未返回该 ETF 行情")
        return _render(
            {
                "quote": DataPoint(quote, "CNY", retrieved_at, retrieved_at, "Tencent Finance", "ok",
                                   "Realtime snapshot; turnover is a percentage, not primary-market fund flow.")
            }
        )
    except Exception as exc:
        return _render({"quote": DataPoint(None, None, None, retrieved_at, "Tencent Finance", "error", str(exc))})


def get_etf_shares_aum(symbol: str) -> str:
    """Return the latest disclosed shares/AUM table; disclosure is not realtime."""
    retrieved_at = _now()
    try:
        response = _em_get(
            "https://fundf10.eastmoney.com/FundArchivesDatas.aspx",
            params={"type": "gmbd", "code": symbol},
            headers=_HEADERS,
        )
        response.raise_for_status()
        tables = pd.read_html(StringIO(response.text))
        if not tables:
            raise RuntimeError("未找到基金规模/份额披露表")
        latest = tables[0].head(2).to_dict(orient="records")
        disclosed_at = str(latest[0].get("日期", "")).strip() if latest else None
        return _render(
            {
                "shares_and_aum": DataPoint(
                    latest, None, disclosed_at or None, retrieved_at, "Eastmoney FundArchivesDatas:gmbd",
                    "stale", "Periodic disclosure; use the table's disclosed period, not retrieval time.",
                )
            }
        )
    except Exception as exc:
        return _render({"shares_and_aum": DataPoint(None, None, None, retrieved_at, "Eastmoney FundArchivesDatas:gmbd", "error", str(exc))})


def get_etf_announcements(symbol: str, end_date: str, limit: int = 10) -> str:
    """Return dated fund announcements, retaining source and publication date."""
    retrieved_at = _now()
    try:
        response = _em_get(
            "https://api.fund.eastmoney.com/f10/JJGG",
            params={"fundcode": symbol, "pageindex": 1, "pagesize": limit, "type": 0},
            headers=_HEADERS,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        data = payload.get("Data", [])
        records = (
            data
            if isinstance(data, list)
            else data.get("List") or data.get("list") or []
        )
        dated = []
        for item in records:
            published_at = str(
                item.get("NOTICE_DATE")
                or item.get("NoticeDate")
                or item.get("PUBLISHDATE")
                or item.get("PUBLISHDATEDesc")
                or ""
            )[:10]
            if published_at and published_at <= end_date:
                dated.append(item)
        return _render(
            {
                "announcements": DataPoint(
                    dated, None, end_date, retrieved_at, "Eastmoney FundF10:JJGG", "ok",
                    "Only announcements published no later than the analysis date are included.",
                )
            }
        )
    except Exception as exc:
        return _render({"announcements": DataPoint(None, None, end_date, retrieved_at, "Eastmoney FundF10:JJGG", "error", str(exc))})


def probe_etf_capabilities(symbol: str, trade_date: str) -> dict[str, str]:
    """Return only capabilities whose validated source failed for this run.

    The probes intentionally use the same adapters as the analysts, so a source
    failure removes the dependent capability before any report section is built.
    Fund identity is excluded because the frozen InstrumentProfile already
    validated it during recognition, avoiding a second costly master lookup.
    Price history/technical data are left enabled here because the downstream
    Sina adapter is independently retried when an analyst requests it.
    """
    probes = {
        "liquidity_metrics": lambda: get_etf_quote(symbol),
        "shares_and_aum": lambda: get_etf_shares_aum(symbol),
        "index_news_policy": lambda: get_etf_announcements(symbol, trade_date),
    }
    unavailable: dict[str, str] = {}
    for capability, fetch in probes.items():
        try:
            payload = json.loads(fetch())
            point = next(iter(payload.values()))
            if point.get("status") in {"error", "missing", "unsupported"}:
                unavailable[capability] = (
                    point.get("notes") or "本次运行的数据源不可用"
                )
        except Exception as exc:
            unavailable[capability] = f"运行时探测失败：{exc}"
    return unavailable
