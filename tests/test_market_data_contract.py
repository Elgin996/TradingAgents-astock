"""Phase 0/1 failure classification and routing regression tests."""

import pandas as pd
import pytest

from tradingagents.dataflows import a_stock, interface
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


def test_exhausted_route_keeps_typed_vendor_error(monkeypatch):
    def unavailable(*args, **kwargs):
        raise ConnectionError("upstream disconnected")

    monkeypatch.setattr(interface, "get_category_for_method", lambda method: "signal_data")
    monkeypatch.setattr(interface, "get_vendor", lambda category, method=None: "primary")
    monkeypatch.setattr(interface, "VENDOR_METHODS", {"get_fund_flow": {"primary": unavailable}})

    with pytest.raises(VendorError, match="No available vendor for 'get_fund_flow'"):
        interface.route_to_vendor("get_fund_flow", "300308", "2026-08-12", True)


def test_etf_liquidity_summary_uses_exact_sessions_and_names_short_window():
    frame = pd.DataFrame(
        {
            "Date": pd.date_range("2026-08-03", periods=7, freq="D"),
            "Volume": [100, 200, 300, 400, 500, 600, 700],
        }
    )

    lines = a_stock._etf_liquidity_summary_lines(frame)
    rendered = "\n".join(lines)

    assert "latest-5 session dates: 2026-08-05,2026-08-06,2026-08-07,2026-08-08,2026-08-09" in rendered
    assert "latest-5 average Volume (shares): 500.00" in rendered
    assert "latest-20 average Volume: UNAVAILABLE (only 7 sessions supplied)" in rendered
    assert "supplied-window average Volume (shares; 7 sessions): 400.00" in rendered
