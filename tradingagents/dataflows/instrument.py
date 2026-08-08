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
            source="user" if record.tracking_index_code_source == "user_supplied" else "security_master",
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
        price_limit_pct=DataPoint(
            10, "%", None, retrieved_at, "conservative ETF rule", "assumed",
            "ETF-specific limit could not be verified; 10% is a conservative assumption.",
        ),
    )
