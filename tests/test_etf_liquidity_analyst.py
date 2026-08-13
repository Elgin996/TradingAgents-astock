from langchain_core.messages import ToolMessage

from tradingagents.agents.analysts.etf_liquidity_analyst import (
    _render_grounded_liquidity_report,
)


def test_liquidity_report_uses_deterministic_tool_statistics():
    history = """# ETF data for 159530
# Deterministic ETF liquidity observations: 7 sessions
# Deterministic latest completed bar date: 2026-08-12
# Deterministic latest-5 session dates: 2026-08-06,2026-08-07,2026-08-10,2026-08-11,2026-08-12
# Deterministic latest-5 average Volume (shares): 500000000.00
# Deterministic latest-20 average Volume: UNAVAILABLE (only 7 sessions supplied)
# Deterministic supplied-window average Volume (shares; 7 sessions): 450000000.00
# Note: Amount (成交额) is unavailable from this source
Date,Open,High,Low,Close,Volume
2026-08-12,1.4,1.5,1.3,1.4,400000000
"""
    quote = '{"quote":{"value":{"price":1.42,"last_close":1.4,"change_pct":1.43,"turnover_pct":2.9},"source":"Tencent Finance"}}'
    report = _render_grounded_liquidity_report(
        [
            ToolMessage(history, name="get_stock_data", tool_call_id="1"),
            ToolMessage(quote, name="get_etf_quote", tool_call_id="2"),
        ],
        "159530",
        "2026-08-13",
    )
    assert report is not None
    assert "最近 5 日均量 | 500,000,000 股（5.00 亿股）" in report
    assert "最近 20 日均量 | 不可得" in report
    assert "当前工具窗口均量 | 450,000,000 股（4.50 亿股）" in report
    assert "不据此推断休市" in report


def test_liquidity_report_does_not_claim_amount_source_when_history_failed():
    report = _render_grounded_liquidity_report(
        [
            ToolMessage(
                "# DATA_UNAVAILABLE: source offline",
                name="get_stock_data",
                tool_call_id="1",
            )
        ],
        "159530",
        "2026-08-13",
    )

    assert report is not None
    assert "日线来源：不可得" in report
    assert "成交量窗口和成交额均不可得" in report
