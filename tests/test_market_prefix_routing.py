"""Market-prefix routing for 6-digit A-share codes.

Regression cover for issue #85: the Beijing Stock Exchange started issuing
920xxx codes for new listings in October 2024.  A bare ``startswith("9")``
routed them to Shanghai, where the Tencent quote endpoint answers with an
empty payload instead of an error — so the failure was silent.
"""

import unittest

import pytest

from tradingagents.dataflows.a_stock import (
    _eastmoney_secid,
    _get_prefix,
    _sina_stock_code,
)


@pytest.mark.unit
class MarketPrefixRoutingTests(unittest.TestCase):

    def test_shanghai_main_board_and_star(self):
        self.assertEqual(_get_prefix("600519"), "sh")
        self.assertEqual(_get_prefix("601398"), "sh")
        self.assertEqual(_get_prefix("688017"), "sh")

    def test_shenzhen_main_board_and_chinext(self):
        self.assertEqual(_get_prefix("000001"), "sz")
        self.assertEqual(_get_prefix("002463"), "sz")
        self.assertEqual(_get_prefix("300476"), "sz")

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

    def test_shanghai_etf_prefix_is_sh(self):
        self.assertEqual(_get_prefix("510300"), "sh")
        self.assertEqual(_get_prefix("517520"), "sh")
        self.assertEqual(_sina_stock_code("517520"), "sh517520")
        self.assertEqual(_eastmoney_secid("510300"), "1.510300")

    def test_call_sites_do_not_send_920_to_shanghai(self):
        """Sina / Eastmoney must reuse _get_prefix, not a bare startswith 5/6/9."""
        self.assertEqual(_sina_stock_code("920002"), "bj920002")
        self.assertEqual(_eastmoney_secid("920002"), "0.920002")
        self.assertEqual(_eastmoney_secid("900901"), "1.900901")


if __name__ == "__main__":
    unittest.main()
