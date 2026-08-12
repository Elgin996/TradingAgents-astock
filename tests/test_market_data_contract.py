"""Phase 0/1 failure classification and routing regression tests."""

import pandas as pd
import pytest

from tradingagents.dataflows import interface
from tradingagents.dataflows.vendors.base import (
    VendorEmptyResult,
    VendorError,
    classify_legacy_result,
)


def test_legacy_error_text_is_not_success():
    with pytest.raises(VendorError):
        classify_legacy_result("K线数据获取失败：服务不可用", source="fixture")


def test_empty_legacy_payload_is_classified():
    with pytest.raises(VendorEmptyResult):
        classify_legacy_result(pd.DataFrame(), source="fixture")


def test_route_falls_back_on_regular_exception(monkeypatch):
    calls = []

    def primary(*args, **kwargs):
        calls.append("primary")
        raise RuntimeError("connection reset")

    def fallback(*args, **kwargs):
        calls.append("fallback")
        return "valid report"

    monkeypatch.setattr(interface, "get_category_for_method", lambda method: "core_stock_apis")
    monkeypatch.setattr(interface, "get_vendor", lambda category, method=None: "primary")
    monkeypatch.setattr(interface, "VENDOR_METHODS", {"get_stock_data": {"primary": primary, "fallback": fallback}})
    assert interface.route_to_vendor("get_stock_data", "600000", "2024-01-01", "2024-01-02") == "valid report"
    assert calls == ["primary", "fallback"]
