"""Phase 4 lookahead: tool classification and Alpha Vantage date filter."""

import json

from tradingagents.dataflows import a_stock
from tradingagents.dataflows.alpha_vantage_fundamentals import _filter_reports_by_date


def test_every_exported_tool_is_classified():
    exported = {
        n
        for n in dir(a_stock)
        if n.startswith("get_") and callable(getattr(a_stock, n))
    }
    unclassified = exported - a_stock.LIVE_ONLY_TOOLS - a_stock.POINT_IN_TIME_TOOLS
    assert not unclassified, (
        f"classify these in LIVE_ONLY_TOOLS or POINT_IN_TIME_TOOLS: {unclassified}"
    )


def test_live_and_pit_sets_are_disjoint():
    overlap = a_stock.LIVE_ONLY_TOOLS & a_stock.POINT_IN_TIME_TOOLS
    assert not overlap


def test_reject_if_not_point_in_time_off_by_default(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.dataflows.config.get_config",
        lambda: {"strict_point_in_time": False},
    )
    assert a_stock._reject_if_not_point_in_time("2020-01-01", "get_fund_flow") is None


def test_reject_if_not_point_in_time_blocks_past(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.dataflows.config.get_config",
        lambda: {"strict_point_in_time": True},
    )
    msg = a_stock._reject_if_not_point_in_time("2020-01-01", "get_fund_flow")
    assert msg is not None
    assert "get_fund_flow" in msg
    assert "2020-01-01" in msg


def test_parse_news_time_formats():
    assert a_stock._parse_news_time("2026-05-12").strftime("%Y-%m-%d") == "2026-05-12"
    assert a_stock._parse_news_time("2026-05-12 15:30").hour == 15
    assert a_stock._parse_news_time("not-a-date") is None
    assert a_stock._parse_news_time("") is None


def test_filter_strips_future_fiscal_periods():
    payload = json.dumps(
        {
            "quarterlyReports": [
                {"fiscalDateEnding": "2026-03-31"},
                {"fiscalDateEnding": "2026-09-30"},
            ]
        }
    )
    out = json.loads(_filter_reports_by_date(payload, "2026-06-30"))
    assert [r["fiscalDateEnding"] for r in out["quarterlyReports"]] == ["2026-03-31"]


def test_get_fundamentals_omits_future_quarterly_rows(monkeypatch):
    import pandas as pd

    frame = pd.DataFrame(
        {"updated_date": [20240930, 20231231], "eps": [9.9, 1.1]}
    )

    class _Client:
        def finance(self, symbol):
            return frame

    monkeypatch.setattr(a_stock, "_get_mootdx_client", lambda: _Client())
    monkeypatch.setattr(
        "tradingagents.dataflows.config.get_config",
        lambda: {"strict_point_in_time": True},
    )
    out = a_stock.get_fundamentals("600519", curr_date="2024-01-15")
    assert "1.1" in out
    assert "9.9" not in out


def test_get_fundamentals_omits_block_when_no_date_column(monkeypatch):
    import pandas as pd

    frame = pd.DataFrame({"eps": [9.9]})

    class _Client:
        def finance(self, symbol):
            return frame

    monkeypatch.setattr(a_stock, "_get_mootdx_client", lambda: _Client())
    monkeypatch.setattr(
        "tradingagents.dataflows.config.get_config",
        lambda: {"strict_point_in_time": True},
    )
    out = a_stock.get_fundamentals("600519", curr_date="2024-01-15")
    assert "EPS" not in out
    assert "9.9" not in out
