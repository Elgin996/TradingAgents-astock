"""Sina daily K-line adapter."""

from __future__ import annotations

from typing import Any, Callable

from ..models import MarketDataRequest, VendorBarsResult, VendorCapabilities
from .base import bars_from_dataframe


class SinaAdapter:
    name = "sina"
    capabilities = VendorCapabilities(
        instrument_types={"stock", "etf", "index"},
        frequencies={"1d"},
        adjustments={"unknown", "raw"},
        provides_amount=False,
    )

    def __init__(self, fetcher: Callable[..., Any] | None = None):
        self.fetcher = fetcher

    def fetch_bars(self, request: MarketDataRequest) -> VendorBarsResult:
        if self.fetcher is None:
            from ..a_stock import _sina_kline_fallback

            frame = _sina_kline_fallback(
                request.symbol,
                request.start_date.isoformat(),
                request.end_date.isoformat(),
            )
        else:
            frame = self.fetcher(request)
        return bars_from_dataframe(
            frame,
            request,
            source=self.name,
            adjustment=request.adjustment if request.adjustment else "unknown",
        )
