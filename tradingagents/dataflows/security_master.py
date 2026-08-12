"""Read-only securities-master adapter for ETF identity recognition.

The two sources have deliberately separate responsibilities:

* mootdx's market lists establish the exchange membership without inferring it
  from a code prefix;
* Eastmoney's fund profile supplies the fund type and tracking-index fields
  needed to classify an exchange-traded fund.

``InstrumentProfile`` is built by ``instrument.profile_from_fund_master`` as
soon as ETF identity is confirmed. A provider-qualified tracking-index code is
optional enrichment rather than a prerequisite for ETF analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from io import StringIO
import logging
import re
from typing import Literal

import pandas as pd

from .a_stock import _em_get, _get_mootdx_client
from .index_catalog import lookup_tracking_index_code
from .utils import safe_ticker_component

logger = logging.getLogger(__name__)

FundClassification = Literal[
    "domestic_equity_etf",
    "active_equity_etf",
    "unsupported_fund",
    "not_a_fund",
]
TrackingIndexCodeSource = Literal["missing", "user_supplied", "catalog"]

_PLACEHOLDER_VALUES = frozenset({"---", "--", "-", ""})
_PROFILE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://fund.eastmoney.com/",
}


@dataclass(frozen=True)
class FundMasterRecord:
    """Classified fund metadata from the validated phase-0 sources."""

    symbol: str
    exchange: Literal["SSE", "SZSE"] | None
    fund_name: str
    fund_type: str
    tracking_index_name: str | None
    fund_manager: str | None
    listed_or_established_date: str | None
    management_fee: str | None
    custodian_fee: str | None
    classification: FundClassification
    classification_reason: str
    tracking_index_code: str | None = None
    tracking_index_provider: str | None = None
    tracking_index_code_source: TrackingIndexCodeSource = "missing"
    etf_management_style: Literal["passive", "active"] | None = None
    benchmark_name: str | None = None


def _text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


@lru_cache(maxsize=8)
def _exchange_memberships(as_of: str) -> dict[str, Literal["SSE", "SZSE"]]:
    """Return exchange membership from the mootdx securities master.

    ``as_of`` is the calendar day string so the membership snapshot refreshes
    daily without staying stale across sessions. Cross-listed codes keep the
    first market written (SZSE before SSE) so Shenzhen equities such as
    ``000016`` are not overwritten by Shanghai index membership.
    """
    del as_of  # cache key only
    client = _get_mootdx_client()
    memberships: dict[str, Literal["SSE", "SZSE"]] = {}
    for market, exchange in ((0, "SZSE"), (1, "SSE")):
        securities = client.stocks(market=market)
        if securities is None or securities.empty or "code" not in securities:
            raise RuntimeError(f"mootdx returned no {exchange} securities master")
        for code in securities["code"]:
            normalized = str(code).strip()
            if not normalized:
                continue
            existing = memberships.get(normalized)
            if existing is None:
                memberships[normalized] = exchange
            elif existing != exchange:
                logger.debug(
                    "exchange membership conflict for %s: keeping %s, ignoring %s",
                    normalized,
                    existing,
                    exchange,
                )
    return memberships


def _lookup_exchange(symbol: str) -> Literal["SSE", "SZSE"]:
    exchange = _exchange_memberships(date.today().isoformat()).get(symbol)
    if exchange is None:
        raise ValueError(f"{symbol} is absent from the SSE/SZSE securities master")
    return exchange


def _fetch_profile_fields(symbol: str) -> dict[str, str]:
    """Fetch the tabular Eastmoney public fund profile for one code."""
    response = _em_get(
        f"https://fundf10.eastmoney.com/jbgk_{symbol}.html",
        headers=_PROFILE_HEADERS,
        timeout=15,
    )
    response.raise_for_status()

    for table in pd.read_html(StringIO(response.text)):
        if table.shape[1] != 4:
            continue
        fields: dict[str, str] = {}
        for _, row in table.iterrows():
            key_a, value_a, key_b, value_b = (_text(value) for value in row.iloc[:4])
            if key_a and value_a:
                fields[key_a] = value_a
            if key_b and value_b:
                fields[key_b] = value_b
        if "基金全称" in fields and "基金类型" in fields:
            return fields
    raise ValueError(f"{symbol} has no parseable Eastmoney fund profile")


def _is_placeholder(value: str | None) -> bool:
    return value is None or value.strip() in _PLACEHOLDER_VALUES


def _classify(fields: dict[str, str]) -> tuple[FundClassification, str]:
    full_name = fields.get("基金全称")
    fund_type = fields.get("基金类型")
    tracking_index = fields.get("跟踪标的")

    if _is_placeholder(full_name) or _is_placeholder(fund_type):
        return "not_a_fund", "东财档案为占位符，判定为非基金证券"
    assert full_name is not None and fund_type is not None
    if "联接" in full_name:
        return "unsupported_fund", "联接基金不在当前支持范围"
    if "交易型开放式" not in full_name:
        return (
            "unsupported_fund",
            "基金全称不包含“交易型开放式”（货币 ETF / LOF / 场外基金等）",
        )
    if fund_type == "指数型-股票":
        if not tracking_index or tracking_index == "该基金无跟踪标的":
            return "unsupported_fund", "被动股票 ETF 缺少可确认的跟踪标的"
        return "domestic_equity_etf", "交易型开放式、指数型-股票且具有跟踪标的"
    # Active ETFs do not have to disclose a mechanical tracking target.  The
    # fund type must still identify a domestic equity product; overseas,
    # fixed-income, commodity and multi-asset types remain out of scope.
    if "股票" in fund_type and "海外" not in fund_type and not any(
        token in fund_type for token in ("债", "货币", "商品", "黄金", "REIT", "混合")
    ):
        return "active_equity_etf", "交易型开放式、境内股票型主动 ETF"
    if fund_type != "指数型-股票":
        return (
            "unsupported_fund",
            f"基金类型为“{fund_type}”，不属于境内股票 ETF",
        )
    return "unsupported_fund", "无法确认 ETF 管理方式"


@lru_cache(maxsize=512)
def _resolve_fund_master_cached(symbol: str, as_of: str) -> FundMasterRecord:
    """Cached resolver keyed by symbol and calendar day."""
    del as_of  # cache key only
    code = safe_ticker_component(symbol)
    try:
        fields = _fetch_profile_fields(code)
    except Exception:
        logger.error("Eastmoney fund profile fetch/parse failed for %s", code, exc_info=True)
        raise

    classification, reason = _classify(fields)
    exchange: Literal["SSE", "SZSE"] | None
    try:
        exchange = _lookup_exchange(code)
    except ValueError:
        if classification == "domestic_equity_etf":
            raise
        exchange = None

    tracking_index_name = fields.get("跟踪标的")
    tracking_index_code = None
    tracking_index_provider = None
    tracking_index_code_source: TrackingIndexCodeSource = "missing"
    if classification == "domestic_equity_etf":
        catalog_hit = lookup_tracking_index_code(tracking_index_name)
        if catalog_hit:
            tracking_index_code, tracking_index_provider = catalog_hit
            tracking_index_code_source = "catalog"

    return FundMasterRecord(
        symbol=code,
        exchange=exchange,
        fund_name=fields.get("基金简称") or fields["基金全称"],
        fund_type=fields["基金类型"],
        tracking_index_name=tracking_index_name,
        fund_manager=fields.get("基金管理人"),
        listed_or_established_date=fields.get("成立日期/规模"),
        management_fee=fields.get("管理费率"),
        custodian_fee=fields.get("托管费率"),
        classification=classification,
        classification_reason=reason,
        tracking_index_code=tracking_index_code,
        tracking_index_provider=tracking_index_provider,
        tracking_index_code_source=tracking_index_code_source,
        etf_management_style=(
            "passive" if classification == "domestic_equity_etf"
            else "active" if classification == "active_equity_etf"
            else None
        ),
        benchmark_name=fields.get("业绩比较基准"),
    )


def resolve_fund_master(symbol: str) -> FundMasterRecord:
    """Resolve and classify one fund without inferring its exchange or type."""
    return _resolve_fund_master_cached(safe_ticker_component(symbol), date.today().isoformat())


def clear_fund_master_caches() -> None:
    """Test helper: drop day-scoped membership and fund-master caches."""
    _exchange_memberships.cache_clear()
    _resolve_fund_master_cached.cache_clear()


def with_user_supplied_tracking_index_code(
    record: FundMasterRecord,
    *,
    code: str,
    provider: str,
) -> FundMasterRecord:
    """Attach a confirmed index identifier without altering master-data facts."""
    normalized_code = code.strip()
    normalized_provider = provider.strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", normalized_code):
        raise ValueError("跟踪指数代码只能包含字母、数字、点、下划线或连字符，最长 64 位")
    if not re.fullmatch(r"[\w .&()-]{1,64}", normalized_provider):
        raise ValueError("指数供应方名称格式无效，最长 64 位")
    return FundMasterRecord(
        **{
            **record.__dict__,
            "tracking_index_code": normalized_code,
            "tracking_index_provider": normalized_provider,
            "tracking_index_code_source": "user_supplied",
        }
    )
