"""Market-prefix routing for 6-digit A-share codes.

Regression cover for issue #85: the Beijing Stock Exchange started issuing
920xxx codes for new listings in October 2024.  A bare ``startswith("9")``
routed them to Shanghai, where the Tencent quote endpoint answers with an
empty payload instead of an error — so the failure was silent.
"""

import unittest

import pandas as pd
import pytest

from tradingagents.dataflows import a_stock
from tradingagents.dataflows.a_stock import (
    _em_kline_with_amount,
    _em_secid,
    _fmt_yi,
    _get_prefix,
    _index_symbol,
    _sina_kline_fallback,
    _sina_symbol,
)
from tradingagents.dataflows.index_catalog import (
    INDEX_EXCHANGE_BY_CODE,
    _INDEX_CATALOG,
)


@pytest.mark.unit
class MarketPrefixRoutingTests(unittest.TestCase):

    def test_shanghai_main_board_and_star(self):
        self.assertEqual(_get_prefix("600519"), "sh")
        self.assertEqual(_get_prefix("601398"), "sh")
        self.assertEqual(_get_prefix("688017"), "sh")

    def test_shanghai_etf_5_prefix(self):
        for code in ("510300", "512480", "588000"):
            self.assertEqual(_get_prefix(code), "sh", f"{code} must route to sh")

    def test_shenzhen_main_board_and_chinext(self):
        self.assertEqual(_get_prefix("000001"), "sz")
        self.assertEqual(_get_prefix("000016"), "sz")
        self.assertEqual(_get_prefix("002463"), "sz")
        self.assertEqual(_get_prefix("300476"), "sz")

    def test_shenzhen_etf_159_prefix(self):
        self.assertEqual(_get_prefix("159915"), "sz")
        self.assertEqual(_get_prefix("159792"), "sz")

    def test_beijing_legacy_8_prefix(self):
        self.assertEqual(_get_prefix("830799"), "bj")
        self.assertEqual(_get_prefix("871981"), "bj")

    def test_beijing_920_series_routes_to_bj_not_sh(self):
        """920xxx is the Beijing Stock Exchange's new-listing range, not Shanghai."""
        for code in ("920002", "920008", "920098", "920111"):
            self.assertEqual(_get_prefix(code), "bj", f"{code} must route to bj")

    def test_shanghai_b_shares_still_route_to_sh(self):
        """900xxx (Shanghai B shares) is the only leading-9 range that really is Shanghai."""
        self.assertEqual(_get_prefix("900901"), "sh")
        self.assertEqual(_get_prefix("900932"), "sh")


@pytest.mark.unit
@pytest.mark.parametrize("code,secid,sina", [
    ("600519", "1.600519", "sh600519"),
    ("510300", "1.510300", "sh510300"),
    ("000001", "0.000001", "sz000001"),
    ("000016", "0.000016", "sz000016"),
    ("300750", "0.300750", "sz300750"),
    ("159915", "0.159915", "sz159915"),
    ("920819", "0.920819", "bj920819"),
    ("832000", "0.832000", "bj832000"),
])
def test_market_routing(code, secid, sina):
    assert _em_secid(code) == secid
    assert _sina_symbol(code) == sina


@pytest.mark.unit
def test_index_symbol_uses_catalog_exchange():
    assert _index_symbol("000906") == "sh000906"
    assert _index_symbol("000510") == "sh000510"
    assert _index_symbol("399006") == "sz399006"
    assert _index_symbol("000300") == "sh000300"


@pytest.mark.unit
def test_structured_index_fetch_uses_explicit_exchange(monkeypatch):
    captured = {}

    class _Response:
        text = "[]"

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"klines": []}}

    def fake_get(url, **kwargs):
        captured[url] = kwargs["params"]
        return _Response()

    monkeypatch.setattr(a_stock._requests, "get", fake_get)
    monkeypatch.setattr(a_stock, "_em_get", fake_get)

    _sina_kline_fallback("000300", exchange="SSE")
    _em_kline_with_amount("000300", adjustment="raw", exchange="SSE")

    sina_params = next(value for key, value in captured.items() if "sina.com" in key)
    eastmoney_params = next(value for key, value in captured.items() if "eastmoney.com" in key)
    assert sina_params["symbol"] == "sh000300"
    assert eastmoney_params["secid"] == "1.000300"


@pytest.mark.unit
def test_index_exchange_covers_catalog_codes():
    catalog_codes = {code for code, _ in _INDEX_CATALOG.values()}
    assert set(INDEX_EXCHANGE_BY_CODE) == catalog_codes



@pytest.mark.unit
def test_fmt_yi_normalizes_raw_yuan():
    assert _fmt_yi(1e8) == "1.00 亿元"
    assert _fmt_yi(2.5e10) == "250.00 亿元"
    assert _fmt_yi("not-a-number") == "N/A"


@pytest.mark.unit
def test_name_map_includes_shanghai_and_shenzhen_etfs(monkeypatch):
    """Name resolution must retain ETF rows returned by mootdx."""
    class FakeClient:
        def stocks(self, market):
            rows = {
                0: [{"code": "159915", "name": "创业板ETF"}],
                1: [{"code": "510300", "name": "沪深300ETF"}],
                2: [],
            }[market]
            return pd.DataFrame(rows, columns=["code", "name"])

    monkeypatch.setattr(a_stock, "_name_to_code", None)
    monkeypatch.setattr(a_stock, "_code_to_name", None)
    monkeypatch.setattr(a_stock, "_get_mootdx_client", FakeClient)

    assert a_stock.resolve_ticker("沪深300ETF") == "510300"
    assert a_stock.resolve_ticker("创业板ETF") == "159915"


if __name__ == "__main__":
    unittest.main()
