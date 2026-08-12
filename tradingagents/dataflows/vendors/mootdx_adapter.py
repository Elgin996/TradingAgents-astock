"""mootdx adapter; network and vendor-specific parsing stay here."""

from __future__ import annotations

from typing import Any, Callable

from ..models import MarketDataRequest, VendorBarsResult, VendorCapabilities
from .base import VendorEmptyResult, VendorNetworkError, bars_from_dataframe


class MootdxAdapter:
    name = "mootdx"
    capabilities = VendorCapabilities(
        instrument_types={"stock"},
        frequencies={"1d"},
        adjustments={"unknown", "raw"},
        provides_amount=False,
    )

    def __init__(self, fetcher: Callable[..., Any] | None = None):
        self.fetcher = fetcher

    def fetch_bars(self, request: MarketDataRequest) -> VendorBarsResult:
        try:
            if self.fetcher is None:
                from ..a_stock import _load_ohlcv_astock

                frame = _load_ohlcv_astock(request.symbol, request.end_date.isoformat())
            else:
                frame = self.fetcher(request)
            return bars_from_dataframe(
                frame,
                request,
                source=self.name,
                adjustment=request.adjustment,
            )
        except (VendorEmptyResult,):
            raise
        except Exception as exc:
            if isinstance(exc, (ValueError, TypeError, KeyError)):
                raise VendorNetworkError(f"mootdx fetch failed: {exc}") from exc
            raise
