"""Vendor adapters for the structured market-data service."""

from .base import (
    MarketDataVendor,
    VendorEmptyResult,
    VendorError,
    VendorNetworkError,
    VendorRateLimited,
    VendorSchemaError,
    VendorStaleResult,
    VendorTimeout,
    VendorUnsupportedRequest,
    classify_legacy_result,
)

__all__ = [
    "MarketDataVendor",
    "VendorError",
    "VendorTimeout",
    "VendorRateLimited",
    "VendorNetworkError",
    "VendorSchemaError",
    "VendorEmptyResult",
    "VendorStaleResult",
    "VendorUnsupportedRequest",
    "classify_legacy_result",
]
