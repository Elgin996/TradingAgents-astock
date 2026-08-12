"""Shared vendor protocol, errors, and legacy-result classification."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..models import MarketDataRequest, VendorBarsResult, VendorCapabilities


class VendorError(RuntimeError):
    status = "network_error"
    error_code = "vendor_error"

    def __init__(self, message: str, *, error_code: str | None = None):
        super().__init__(message)
        if error_code:
            self.error_code = error_code


class VendorTimeout(VendorError):
    status = "timeout"
    error_code = "timeout"


class VendorRateLimited(VendorError):
    status = "rate_limited"
    error_code = "rate_limited"


class VendorNetworkError(VendorError):
    status = "network_error"
    error_code = "network_error"


class VendorSchemaError(VendorError):
    status = "schema_error"
    error_code = "schema_error"


class VendorEmptyResult(VendorError):
    status = "empty"
    error_code = "empty"


class VendorStaleResult(VendorError):
    status = "stale"
    error_code = "stale"


class VendorUnsupportedRequest(VendorError):
    status = "unsupported"
    error_code = "unsupported"


class MarketDataVendor(Protocol):
    name: str
    capabilities: VendorCapabilities

    def fetch_bars(self, request: MarketDataRequest) -> VendorBarsResult:
        ...


_ERROR_PREFIXES = (
    "error",
    "no data",
    "no ",
    "获取失败",
    "无法获取",
    "数据获取失败",
    "k线数据获取失败",
)


def _safe_summary(value: object, max_length: int = 240) -> str:
    """Return a short, credential-safe error summary for logs/attempts."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"(?i)(api[_ -]?key|token|cookie|authorization)\s*[:=]\s*\S+", r"\1=<redacted>", text)
    text = re.sub(r"https?://[^\s]+", "<url-redacted>", text)
    return text[:max_length]


def classify_legacy_result(result: Any, *, source: str = "legacy") -> Any:
    """Classify old tool return values without letting error text become data.

    Non-empty strings that do not look like an error are returned unchanged so
    this helper can be used by the compatibility router.  Empty tabular
    results and known error prefixes raise the structured exception expected by
    the new service.
    """
    if result is None:
        raise VendorEmptyResult(f"{source} returned no result")
    if hasattr(result, "empty") and bool(result.empty):
        raise VendorEmptyResult(f"{source} returned an empty table")
    if isinstance(result, (list, tuple, dict)) and not result:
        raise VendorEmptyResult(f"{source} returned an empty payload")
    if isinstance(result, str):
        stripped = result.strip()
        if not stripped:
            raise VendorEmptyResult(f"{source} returned an empty response")
        lowered = stripped.lower()
        if lowered.startswith(_ERROR_PREFIXES) or "获取失败" in stripped or "无法获取" in stripped:
            raise VendorError(_safe_summary(stripped), error_code="legacy_error_text")
    return result


def classify_exception(exc: Exception) -> VendorError:
    """Map common third-party failures to the stable vendor error taxonomy."""
    if isinstance(exc, VendorError):
        return exc
    name = type(exc).__name__.lower()
    message = _safe_summary(exc)
    lowered = message.lower()
    if "timeout" in name or "timed out" in lowered:
        return VendorTimeout(message)
    if "rate" in lowered and ("limit" in lowered or "too many" in lowered):
        return VendorRateLimited(message)
    if "schema" in name or "column" in lowered or "parse" in lowered:
        return VendorSchemaError(message)
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return VendorSchemaError(message)
    return VendorNetworkError(message)


def bars_from_dataframe(
    frame: Any,
    request: MarketDataRequest,
    *,
    source: str,
    source_symbol: str | None = None,
    adjustment: str = "unknown",
) -> VendorBarsResult:
    """Normalize a vendor DataFrame with a deliberately small schema surface."""
    try:
        import pandas as pd
        from ..models import NormalizedBar

        if frame is None or frame.empty:
            raise VendorEmptyResult(f"{source} returned no bars")
        aliases = {
            "date": "trade_date",
            "datetime": "trade_date",
            "Date": "trade_date",
            "日期": "trade_date",
            "open": "open",
            "Open": "open",
            "high": "high",
            "High": "high",
            "low": "low",
            "Low": "low",
            "close": "close",
            "Close": "close",
            "volume": "volume",
            "Volume": "volume",
            "amount": "amount",
            "Amount": "amount",
        }
        renamed = frame.rename(columns={k: v for k, v in aliases.items() if k in frame.columns}).copy()
        required = {"trade_date", "open", "high", "low", "close"}
        missing = required - set(renamed.columns)
        if missing:
            raise VendorSchemaError(f"{source} missing columns: {sorted(missing)}")
        renamed["trade_date"] = pd.to_datetime(renamed["trade_date"], errors="coerce").dt.date
        if renamed["trade_date"].isna().any():
            raise VendorSchemaError(f"{source} returned invalid trade dates")
        bars = []
        retrieved_at = datetime.now().astimezone()
        for row in renamed.sort_values("trade_date").itertuples(index=False):
            values = row._asdict()

            def decimal_value(name: str) -> Decimal | None:
                value = values.get(name)
                if value is None or (isinstance(value, float) and value != value):
                    return None
                return Decimal(str(value))

            bars.append(
                NormalizedBar(
                    symbol=request.symbol,
                    trade_date=values["trade_date"],
                    open=decimal_value("open"),
                    high=decimal_value("high"),
                    low=decimal_value("low"),
                    close=decimal_value("close"),
                    volume=decimal_value("volume"),
                    amount=decimal_value("amount"),
                    adjustment=adjustment,
                    source=source,
                    source_symbol=source_symbol or request.symbol,
                    retrieved_at=retrieved_at,
                )
            )
        return VendorBarsResult(source=source, bars=bars, adjustment=adjustment)
    except VendorError:
        raise
    except Exception as exc:
        raise VendorSchemaError(f"{source} response normalization failed: {_safe_summary(exc)}") from exc


@dataclass(frozen=True)
class LegacyVendorAdapter:
    """Small adapter useful while migrating a legacy function to the service."""

    name: str
    fetch: Any
    capabilities: VendorCapabilities = field(default_factory=VendorCapabilities)

    def fetch_bars(self, request: MarketDataRequest) -> VendorBarsResult:
        try:
            result = classify_legacy_result(self.fetch(request), source=self.name)
        except Exception as exc:
            raise classify_exception(exc) from exc
        if not isinstance(result, VendorBarsResult):
            raise VendorSchemaError(f"{self.name} adapter did not return VendorBarsResult")
        return result
