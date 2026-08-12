"""Frozen, serializable identity and data records for an analysis run."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from .models import ReferenceInstrument
from .security_master import FundMasterRecord, with_user_supplied_tracking_index_code

DataStatus = Literal["ok", "stale", "missing", "unsupported", "error", "assumed", "derived"]


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
    security_type: Literal["stock", "etf", "index"]
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
    # v2 identity and relationship fields.  Defaults preserve old checkpoints
    # and callers that still construct the phase-1 dataclass directly.
    analysis_product: Literal[
        "a_share_stock", "passive_equity_etf", "active_equity_etf"
    ] = "a_share_stock"
    instrument_id: str | None = None
    name: str | None = None
    timezone: str = "Asia/Shanghai"
    adjustment_policy: str = "raw"
    etf_management_style: Literal["passive", "active"] | None = None
    reference_instrument: ReferenceInstrument | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.reference_instrument is not None:
            payload["reference_instrument"] = self.reference_instrument.model_dump(mode="json")
        return payload


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def profile_from_fund_master(
    record: FundMasterRecord,
    *,
    user_tracking_index_code: str | None = None,
    user_tracking_index_provider: str | None = None,
) -> InstrumentProfile:
    """Build an ETF profile only from a confirmed, in-scope master record."""
    if record.classification not in {"domestic_equity_etf", "active_equity_etf"}:
        raise ValueError(f"当前版本不支持该产品：{record.classification_reason}")
    if user_tracking_index_code is not None or user_tracking_index_provider is not None:
        record = with_user_supplied_tracking_index_code(
            record,
            code=user_tracking_index_code or "",
            provider=user_tracking_index_provider or "",
        )
    retrieved_at = utc_now()
    price_limit = derive_price_limit_pct(
        symbol=record.symbol,
        fund_name=record.fund_name,
        tracking_index_name=record.tracking_index_name,
        retrieved_at=retrieved_at,
    )
    analysis_product = (
        "active_equity_etf"
        if record.etf_management_style == "active"
        else "passive_equity_etf"
    )
    reference = None
    reference_name = (
        record.tracking_index_name
        if analysis_product == "passive_equity_etf"
        else record.benchmark_name
    )
    if record.tracking_index_code and record.tracking_index_provider:
        from .index_master import resolve_index_reference

        reference = resolve_index_reference(
            name=reference_name,
            code=record.tracking_index_code,
            provider=record.tracking_index_provider,
            role="tracking_index" if analysis_product == "passive_equity_etf" else "benchmark",
            user_supplied=record.tracking_index_code_source == "user_supplied",
            verified_at=retrieved_at,
        )
    elif reference_name:
        reference = ReferenceInstrument(
            role="tracking_index" if analysis_product == "passive_equity_etf" else "benchmark",
            name=reference_name,
            source="security_master",
            status="missing",
            verified_at=retrieved_at,
        )
    return InstrumentProfile(
        symbol=record.symbol,
        exchange=record.exchange,
        security_type="etf",
        etf_asset_type="domestic_equity",
        fund_name=record.fund_name,
        tracking_index_name=record.tracking_index_name,
        tracking_index_code=(
            DataPoint(
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
            )
            if record.tracking_index_code and record.tracking_index_provider
            else None
        ),
        profile_as_of=datetime.now(timezone.utc).date().isoformat(),
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
        analysis_product=analysis_product,
        instrument_id=f"ETF:{record.exchange}:{record.symbol}",
        name=record.fund_name,
        timezone="Asia/Shanghai",
        adjustment_policy="forward",
        etf_management_style=record.etf_management_style or "passive",
        reference_instrument=reference,
    )


def profile_for_stock(
    symbol: str,
    *,
    exchange: Literal["SSE", "SZSE", "BSE"],
    name: str | None = None,
    as_of: str | None = None,
) -> InstrumentProfile:
    """Freeze a normal A-share stock identity without ETF semantics."""

    retrieved_at = utc_now()
    return InstrumentProfile(
        symbol=symbol.strip(),
        exchange=exchange,
        security_type="stock",
        etf_asset_type=None,
        fund_name=None,
        tracking_index_name=None,
        tracking_index_code=None,
        profile_as_of=as_of or retrieved_at[:10],
        source="security_master",
        currency=DataPoint("CNY", "currency", None, retrieved_at, "scope constant", "ok"),
        analysis_product="a_share_stock",
        instrument_id=f"STOCK:{exchange}:{symbol.strip()}",
        name=name,
        timezone="Asia/Shanghai",
        adjustment_policy="forward",
    )


def profile_for_index(
    *,
    code: str,
    provider: str,
    name: str,
    exchange: Literal["SSE", "SZSE", "BSE"],
    series_variant: Literal["price", "total_return", "net_total_return", "unknown"] = "price",
    as_of: str | None = None,
    source: str = "index_master",
) -> InstrumentProfile:
    """Freeze a non-tradable index identity for ETF sub-analysis."""

    retrieved_at = utc_now()
    reference = ReferenceInstrument(
        role="tracking_index",
        code=code,
        name=name,
        provider=provider,
        series_variant=series_variant,
        source=source,
        status="verified",
        verified_at=as_of or retrieved_at,
        instrument_id=f"{provider}:{code}:{series_variant}",
    )
    return InstrumentProfile(
        symbol=code,
        exchange=exchange,
        security_type="index",
        etf_asset_type=None,
        fund_name=None,
        tracking_index_name=name,
        tracking_index_code=DataPoint(
            value={"code": code, "provider": provider},
            unit=None,
            as_of=as_of,
            retrieved_at=retrieved_at,
            source=source,
            status="ok",
            notes=series_variant,
        ),
        profile_as_of=as_of or retrieved_at[:10],
        source=source,
        currency=DataPoint("CNY", "currency", None, retrieved_at, "scope constant", "ok"),
        analysis_product="a_share_stock",
        instrument_id=f"{provider}:{code}:{series_variant}",
        name=name,
        timezone="Asia/Shanghai",
        adjustment_policy="raw",
        reference_instrument=reference,
    )


def infer_analysis_product(
    profile: InstrumentProfile | dict[str, Any] | None,
) -> Literal["a_share_stock", "passive_equity_etf", "active_equity_etf"]:
    """Return a product route from frozen identity, failing closed on unknowns."""

    if profile is None:
        raise ValueError("instrument profile is required to infer analysis product")
    data = profile.to_dict() if isinstance(profile, InstrumentProfile) else profile
    explicit = data.get("analysis_product")
    # Phase-1 ETF checkpoints predate ``analysis_product`` and may materialize
    # the dataclass default of ``a_share_stock``.  Security type remains the
    # stronger legacy discriminator for that shape.
    if data.get("security_type") == "etf" and explicit == "a_share_stock":
        if data.get("etf_management_style") == "active":
            return "active_equity_etf"
        return "passive_equity_etf"
    if explicit in {"a_share_stock", "passive_equity_etf", "active_equity_etf"}:
        return explicit
    security_type = data.get("security_type")
    if security_type == "stock":
        return "a_share_stock"
    if security_type == "etf":
        style = data.get("etf_management_style")
        if style == "active":
            return "active_equity_etf"
        if style == "passive":
            return "passive_equity_etf"
    raise ValueError("unable to determine analysis product from frozen instrument identity")


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
