"""Eastmoney daily K-line adapter."""

from __future__ import annotations

from typing import Any, Callable

from ..models import MarketDataRequest, VendorBarsResult, VendorCapabilities
from .base import bars_from_dataframe


class EastmoneyAdapter:
    name = "eastmoney"
    capabilities = VendorCapabilities(
        instrument_types={"stock", "etf", "index"},
        frequencies={"1d"},
        adjustments={"unknown", "raw", "forward", "backward"},
        provides_amount=True,
    )

    def __init__(self, fetcher: Callable[..., Any] | None = None):
        self.fetcher = fetcher

    def fetch_bars(self, request: MarketDataRequest) -> VendorBarsResult:
        if self.fetcher is None:
            from ..a_stock import _em_kline_with_amount

            exchange_kwargs = (
                {"exchange": request.exchange}
                if request.instrument_type == "index"
                else {}
            )
            frame = _em_kline_with_amount(
                request.symbol,
                request.start_date.isoformat(),
                request.end_date.isoformat(),
                request.adjustment,
                **exchange_kwargs,
            )
        else:
            frame = self.fetcher(request)
        return bars_from_dataframe(
            frame,
            request,
            source=self.name,
            adjustment=request.adjustment,
        )
