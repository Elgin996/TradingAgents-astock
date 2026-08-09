"""Frozen, serializable identity and data records for an analysis run."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from .security_master import FundMasterRecord, with_user_supplied_tracking_index_code

DataStatus = Literal["ok", "stale", "missing", "unsupported", "error", "assumed"]


@dataclass(frozen=True)
class DataPoint:
    value: Any
    unit: str | None
    as_of: str | None
    retrieved_at: str
    source: str
    status: DataStatus
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InstrumentProfile:
    symbol: str
    exchange: str
    security_type: Literal["stock", "etf"]
    etf_asset_type: str | None
    fund_name: str | None
    tracking_index_name: str | None
    tracking_index_code: DataPoint | None
    profile_as_of: str
    source: str
    fund_manager: DataPoint | None = None
    listed_date: DataPoint | None = None
    currency: DataPoint | None = None
    turnaround_rule: DataPoint | None = None
    lot_size: DataPoint | None = None
    price_limit_pct: DataPoint | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def profile_from_fund_master(
    record: FundMasterRecord,
    *,
    user_tracking_index_code: str | None = None,
    user_tracking_index_provider: str | None = None,
) -> InstrumentProfile:
    """Build an ETF profile only from a confirmed, in-scope master record."""
    if record.classification != "domestic_equity_etf":
        raise ValueError(f"当前版本不支持该产品：{record.classification_reason}")
    if user_tracking_index_code is not None or user_tracking_index_provider is not None:
        record = with_user_supplied_tracking_index_code(
            record,
            code=user_tracking_index_code or "",
            provider=user_tracking_index_provider or "",
        )
    if not record.tracking_index_code or not record.tracking_index_provider:
        raise ValueError("缺少供应方标识的跟踪指数代码")

    retrieved_at = utc_now()
    price_limit = derive_price_limit_pct(
        symbol=record.symbol,
        fund_name=record.fund_name,
        tracking_index_name=record.tracking_index_name,
        retrieved_at=retrieved_at,
    )
    return InstrumentProfile(
        symbol=record.symbol,
        exchange=record.exchange,
        security_type="etf",
        etf_asset_type="domestic_equity",
        fund_name=record.fund_name,
        tracking_index_name=record.tracking_index_name,
        tracking_index_code=DataPoint(
            value={
                "code": record.tracking_index_code,
                "provider": record.tracking_index_provider,
            },
            unit=None,
            as_of=None,
            retrieved_at=retrieved_at,
            source={
                "user_supplied": "user",
                "catalog": "index_catalog",
            }.get(record.tracking_index_code_source, "security_master"),
            status="ok",
            notes=record.tracking_index_code_source,
        ),
        profile_as_of=datetime.now().date().isoformat(),
        source="mootdx securities master + Eastmoney fund profile",
        fund_manager=DataPoint(
            record.fund_manager, None, None, retrieved_at, "Eastmoney FundF10",
            "ok" if record.fund_manager else "missing",
        ),
        listed_date=DataPoint(
            record.listed_or_established_date, None, record.listed_or_established_date,
            retrieved_at, "Eastmoney FundF10",
            "ok" if record.listed_or_established_date else "missing",
        ),
        currency=DataPoint("CNY", "currency", None, retrieved_at, "scope constant", "ok"),
        turnaround_rule=DataPoint("T+1", None, None, retrieved_at, "SSE/SZSE rule", "ok"),
        lot_size=DataPoint(100, "shares", None, retrieved_at, "SSE/SZSE rule", "ok"),
        price_limit_pct=price_limit,
    )


def derive_price_limit_pct(
    *,
    symbol: str,
    fund_name: str | None,
    tracking_index_name: str | None,
    retrieved_at: str | None = None,
) -> DataPoint:
    """Derive ETF daily limit from board/theme hints; otherwise assume 10%.

    No public per-ETF limit API is available. STAR-board listed ETFs (588xxx)
    and names/indices that explicitly reference 科创板/创业板 use 20%; all
    other domestic equity ETFs conservatively assume 10%.
    """
    retrieved_at = retrieved_at or utc_now()
    haystack = f"{symbol} {fund_name or ''} {tracking_index_name or ''}"
    if symbol.startswith("588") or any(
        token in haystack for token in ("科创板", "创业板", "ChiNext", "STAR")
    ):
        return DataPoint(
            20,
            "%",
            None,
            retrieved_at,
            "derived from board/theme naming",
            "derived",
            "Limit inferred from STAR/ChiNext listing or index theme; not an exchange API value.",
        )
    return DataPoint(
        10,
        "%",
        None,
        retrieved_at,
        "conservative ETF rule",
        "assumed",
        "ETF-specific limit could not be verified from board/theme hints; 10% is a conservative assumption.",
    )
