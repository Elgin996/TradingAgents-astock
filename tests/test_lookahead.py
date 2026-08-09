"""Phase 4 lookahead: tool classification and Alpha Vantage date filter."""

import json
from datetime import datetime, timezone

from tradingagents.dataflows import a_stock, etf_data
from tradingagents.dataflows.alpha_vantage_fundamentals import _filter_reports_by_date

_TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
_PAST = "2020-01-01"


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


def test_etf_quote_rejects_past_trade_date_with_no_numeric_values(monkeypatch):
    monkeypatch.setattr(
        etf_data, "_tencent_quote", lambda codes: {codes[0]: {"price": 999.0}}
    )
    payload = json.loads(etf_data.get_etf_quote("510300", _PAST))
    point = payload["quote"]
    assert point["status"] == "unsupported"
    assert point["value"] is None


def test_etf_structure_alerts_rejects_past_trade_date_with_no_numeric_values(monkeypatch):
    monkeypatch.setattr(
        etf_data, "_tencent_quote", lambda codes: {codes[0]: {"turnover_pct": 0.05}}
    )
    payload = json.loads(etf_data.get_etf_structure_alerts("510300", _PAST))
    point = payload["structure_alerts"]
    assert point["status"] == "unsupported"
    assert point["value"] is None


def test_etf_peer_comparison_rejects_past_trade_date_with_no_numeric_values(monkeypatch):
    monkeypatch.setattr(
        etf_data, "resolve_fund_master", lambda symbol: (_ for _ in ()).throw(
            AssertionError("must not resolve fund master for a rejected past date")
        )
    )
    payload = json.loads(etf_data.get_etf_peer_comparison("510300", _PAST))
    point = payload["peer_comparison"]
    assert point["status"] == "unsupported"
    assert point["value"] is None


def test_etf_snapshot_tools_unaffected_for_today_or_future_date(monkeypatch):
    monkeypatch.setattr(
        etf_data, "_tencent_quote", lambda codes: {codes[0]: {"price": 1.5, "turnover_pct": 1.0}}
    )
    monkeypatch.setattr(etf_data, "get_etf_shares_aum", lambda symbol: json.dumps(
        {"shares_and_aum": {"status": "missing", "value": []}}
    ))
    quote_payload = json.loads(etf_data.get_etf_quote("510300", _TODAY))
    assert quote_payload["quote"]["status"] == "ok"

    alerts_payload = json.loads(etf_data.get_etf_structure_alerts("510300", _TODAY))
    assert alerts_payload["structure_alerts"]["status"] in {"ok", "missing"}


def test_probe_etf_capabilities_includes_liquidity_metrics_for_past_date_only_as_unavailable(monkeypatch):
    ok = '{"data": {"status": "ok"}}'
    monkeypatch.setattr(etf_data, "get_etf_profile", lambda symbol: ok)
    monkeypatch.setattr(etf_data, "get_etf_shares_aum", lambda symbol: ok)
    monkeypatch.setattr(etf_data, "get_etf_announcements", lambda symbol, date: ok)

    # Today/future: liquidity_metrics probe should not be forced unavailable by
    # the point-in-time guard (still subject to real source failures).
    monkeypatch.setattr(
        etf_data, "_tencent_quote", lambda codes: {codes[0]: {"price": 1.0}}
    )
    unavailable_today = etf_data.probe_etf_capabilities("510300", _TODAY)
    assert "liquidity_metrics" not in unavailable_today

    unavailable_past = etf_data.probe_etf_capabilities("510300", _PAST)
    assert "liquidity_metrics" in unavailable_past


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
