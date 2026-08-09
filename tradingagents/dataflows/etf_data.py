"""ETF data adapters with auditable field metadata (phases 1 and 3)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from functools import lru_cache
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

# Stage-0 closures that Stage 3 must never claim to compare.
_STAGE3_EXCLUDED = (
    "premium_discount",
    "nav_iopv",
    "tracking_quality",
    "index_exposure",
    "pcf",
)

_SHARE_SPIKE_MEDIUM = 0.10
_SHARE_SPIKE_HIGH = 0.25
_AUM_SHRINK_MEDIUM = -0.15
_AUM_SHRINK_HIGH = -0.30
_THIN_TURNOVER_PCT = 0.30
_LISTED_ETF_CODE = re.compile(r"^(5\d{5}|15\d{4})$")
_INDEX_TOKEN_NOISE = re.compile(
    r"(价格指数|全收益指数|净收益指数|指数|Index)$", re.IGNORECASE
)


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


def _index_search_token(tracking_index_name: str) -> str:
    """Collapse a tracking-index label into the shortest searchable token."""
    token = tracking_index_name.strip()
    token = _INDEX_TOKEN_NOISE.sub("", token).strip()
    return token or tracking_index_name.strip()


def _peer_search_key(tracking_index_name: str) -> str:
    token = _index_search_token(tracking_index_name)
    return token if token.upper().endswith("ETF") else f"{token}ETF"


def _is_listed_etf_candidate(code: str, name: str, fund_type: str | None) -> bool:
    if not _LISTED_ETF_CODE.fullmatch(code):
        return False
    if "联接" in name or "QDII" in name.upper() or "跨境" in name:
        return False
    if fund_type and ("海外" in fund_type or "债券" in fund_type or "商品" in fund_type):
        return False
    return True


def _same_index(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return _index_search_token(left) == _index_search_token(right)


@lru_cache(maxsize=64)
def _fund_search(key: str) -> tuple[dict[str, Any], ...]:
    response = _em_get(
        "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx",
        params={"m": 1, "key": key},
        headers=_HEADERS,
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("Datas") or []
    return tuple(row for row in rows if isinstance(row, dict))


def discover_peer_etf_codes(
    symbol: str,
    tracking_index_name: str,
    *,
    limit: int = 8,
) -> list[str]:
    """Return listed domestic equity ETF codes that share an index search key.

    Discovery is suggestive and always includes ``symbol``. Candidates are
    later verified against fund-profile tracking labels before comparison.
    """
    search_key = _peer_search_key(tracking_index_name)
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(code: str) -> None:
        if code in seen:
            return
        seen.add(code)
        ordered.append(code)

    _add(symbol)
    for row in _fund_search(search_key):
        code = str(row.get("CODE") or "").strip()
        name = str(row.get("NAME") or "")
        fund_type = (row.get("FundBaseInfo") or {}).get("FTYPE")
        if _is_listed_etf_candidate(code, name, fund_type):
            _add(code)
        if len(ordered) >= limit:
            break
    return ordered[:limit]


def _parse_numeric(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text in {"--", "None", "nan"}:
        return None
    try:
        return float(text)
    except ValueError:
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(match.group(0)) if match else None


def _latest_shares_row(symbol: str) -> tuple[dict[str, Any] | None, str | None, str]:
    payload = json.loads(get_etf_shares_aum(symbol))
    point = payload["shares_and_aum"]
    status = point.get("status", "error")
    rows = point.get("value") or []
    if status in {"error", "missing", "unsupported"} or not rows:
        return None, point.get("as_of"), status
    return rows[0], point.get("as_of"), status


def _peer_row(symbol: str, *, is_subject: bool, expected_index: str) -> dict[str, Any] | None:
    try:
        record = resolve_fund_master(symbol)
    except Exception as exc:
        return {
            "symbol": symbol,
            "is_subject": is_subject,
            "status": "error",
            "notes": str(exc),
        }
    if record.classification != "domestic_equity_etf":
        return None
    if not is_subject and not _same_index(record.tracking_index_name, expected_index):
        return None

    quote = _tencent_quote([symbol]).get(symbol) or {}
    shares_row, shares_as_of, shares_status = _latest_shares_row(symbol)
    return {
        "symbol": symbol,
        "is_subject": is_subject,
        "fund_name": record.fund_name,
        "tracking_index_name": record.tracking_index_name,
        "fund_manager": record.fund_manager,
        "management_fee": record.management_fee,
        "custodian_fee": record.custodian_fee,
        "price": quote.get("price"),
        "turnover_pct": quote.get("turnover_pct"),
        "float_mcap_yi": quote.get("float_mcap_yi"),
        "shares_yi": _parse_numeric((shares_row or {}).get("期末总份额（亿份）")),
        "aum_yi": _parse_numeric((shares_row or {}).get("期末净资产（亿元）")),
        "shares_as_of": shares_as_of,
        "shares_status": shares_status,
        "status": "ok",
    }


def get_etf_peer_comparison(symbol: str, max_peers: int = 6) -> str:
    """Compare same-index ETFs on fees, disclosed AUM/shares, and liquidity.

    Intentionally omits premium/discount, tracking error, and holdings exposure
    because those Stage 1.5/2 capabilities remain closed.
    """
    retrieved_at = _now()
    try:
        record = resolve_fund_master(symbol)
        index_name = record.tracking_index_name
        if not index_name:
            raise RuntimeError("缺少跟踪指数名称，无法发现同类 ETF")
        codes = discover_peer_etf_codes(symbol, index_name, limit=max(max_peers, 2))
        peers: list[dict[str, Any]] = []
        for code in codes:
            row = _peer_row(code, is_subject=(code == symbol), expected_index=index_name)
            if row is not None:
                peers.append(row)
            if sum(1 for item in peers if item.get("status") == "ok") >= max_peers:
                break
        ok_peers = [item for item in peers if item.get("status") == "ok"]
        status = "ok" if any(item.get("is_subject") for item in ok_peers) else "error"
        if status == "ok" and len(ok_peers) < 2:
            status = "missing"
        return _render(
            {
                "peer_comparison": DataPoint(
                    {
                        "subject": symbol,
                        "tracking_index_name": index_name,
                        "search_key": _peer_search_key(index_name),
                        "peers": peers,
                        "compared_fields": [
                            "management_fee",
                            "custodian_fee",
                            "shares_yi",
                            "aum_yi",
                            "turnover_pct",
                            "float_mcap_yi",
                        ],
                        "excluded_fields": list(_STAGE3_EXCLUDED),
                    },
                    None,
                    retrieved_at,
                    retrieved_at,
                    "Eastmoney FundSearch + FundF10 + Tencent quote",
                    status,
                    "Peers are listed domestic equity ETFs matched by index search "
                    "key and verified tracking-index labels. Premium, IOPV, tracking "
                    "error, index weights, and PCF are excluded by Stage 0 closures.",
                )
            }
        )
    except Exception as exc:
        return _render(
            {
                "peer_comparison": DataPoint(
                    None,
                    None,
                    None,
                    retrieved_at,
                    "Eastmoney FundSearch + FundF10 + Tencent quote",
                    "error",
                    str(exc),
                )
            }
        )


def _share_history_rows(symbol: str) -> list[dict[str, Any]]:
    payload = json.loads(get_etf_shares_aum(symbol))
    point = payload["shares_and_aum"]
    if point.get("status") in {"error", "missing", "unsupported"}:
        return []
    rows = point.get("value") or []
    return [row for row in rows if isinstance(row, dict)]


def get_etf_structure_alerts(symbol: str) -> str:
    """Emit deterministic alerts for share spikes and thin secondary liquidity.

    Does not alert on premium/discount or tracking error (Stage 1.5/2 closed).
    """
    retrieved_at = _now()
    alerts: list[dict[str, Any]] = []
    try:
        rows = _share_history_rows(symbol)
        if len(rows) >= 2:
            latest, prior = rows[0], rows[1]
            latest_shares = _parse_numeric(latest.get("期末总份额（亿份）"))
            prior_shares = _parse_numeric(prior.get("期末总份额（亿份）"))
            latest_aum = _parse_numeric(latest.get("期末净资产（亿元）"))
            prior_aum = _parse_numeric(prior.get("期末净资产（亿元）"))
            as_of = str(latest.get("日期") or "")
            if latest_shares is not None and prior_shares not in (None, 0):
                share_chg = (latest_shares - prior_shares) / prior_shares
                severity = None
                if abs(share_chg) >= _SHARE_SPIKE_HIGH:
                    severity = "high"
                elif abs(share_chg) >= _SHARE_SPIKE_MEDIUM:
                    severity = "medium"
                if severity:
                    alerts.append(
                        {
                            "rule": "share_change_spike",
                            "severity": severity,
                            "as_of": as_of,
                            "value": round(share_chg, 4),
                            "unit": "ratio",
                            "message": (
                                f"期末总份额较上一披露期变化 {share_chg:.1%} "
                                f"({prior_shares}→{latest_shares} 亿份)"
                            ),
                            "notes": "Based on periodic disclosure, not realtime creations/redemptions.",
                        }
                    )
            aum_chg = None
            disclosed_aum_chg = _parse_numeric(latest.get("净资产变动率"))
            if disclosed_aum_chg is not None:
                aum_chg = disclosed_aum_chg / 100.0
            elif latest_aum is not None and prior_aum not in (None, 0):
                aum_chg = (latest_aum - prior_aum) / prior_aum
            if aum_chg is not None:
                severity = None
                if aum_chg <= _AUM_SHRINK_HIGH:
                    severity = "high"
                elif aum_chg <= _AUM_SHRINK_MEDIUM:
                    severity = "medium"
                if severity:
                    alerts.append(
                        {
                            "rule": "aum_shrink",
                            "severity": severity,
                            "as_of": as_of,
                            "value": round(aum_chg, 4),
                            "unit": "ratio",
                            "message": f"期末净资产较上一披露期变化 {aum_chg:.1%}",
                            "notes": "AUM changes mix share flows and NAV moves; not net subscription.",
                        }
                    )

        quote = _tencent_quote([symbol]).get(symbol)
        if quote is not None:
            turnover = float(quote.get("turnover_pct") or 0.0)
            if turnover > 0 and turnover < _THIN_TURNOVER_PCT:
                alerts.append(
                    {
                        "rule": "liquidity_thin",
                        "severity": "medium" if turnover >= 0.1 else "high",
                        "as_of": retrieved_at[:10],
                        "value": turnover,
                        "unit": "percent",
                        "message": (
                            f"二级市场换手率偏低（{turnover:.2f}% < "
                            f"{_THIN_TURNOVER_PCT:.2f}%）"
                        ),
                        "notes": "Secondary-market turnover snapshot; not primary-market fund flow.",
                    }
                )

        status = "ok" if (rows or quote is not None) else "missing"
        return _render(
            {
                "structure_alerts": DataPoint(
                    {
                        "symbol": symbol,
                        "alerts": alerts,
                        "excluded_rules": [
                            "premium_discount_abnormal",
                            "tracking_error_spike",
                        ],
                    },
                    None,
                    retrieved_at,
                    retrieved_at,
                    "Eastmoney FundArchivesDatas:gmbd + Tencent quote",
                    status,
                    "Rule alerts cover disclosed share/AUM shifts and thin turnover only.",
                )
            }
        )
    except Exception as exc:
        return _render(
            {
                "structure_alerts": DataPoint(
                    None,
                    None,
                    None,
                    retrieved_at,
                    "Eastmoney FundArchivesDatas:gmbd + Tencent quote",
                    "error",
                    str(exc),
                )
            }
        )


def probe_etf_capabilities(symbol: str, trade_date: str) -> dict[str, str]:
    """Return only capabilities whose validated source failed for this run.

    The probes intentionally use the same adapters as the analysts, so a source
    failure removes the dependent capability before any report section is built.
    Fund identity is excluded because the frozen InstrumentProfile already
    validated it during recognition, avoiding a second costly master lookup.
    Price history/technical data are left enabled here because the downstream
    Sina adapter is independently retried when an analyst requests it.
    """
    # peer_comparison is intentionally not probed here: discovery fans out to
    # several Eastmoney calls and would double the Stage-3 analyst cost.
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
