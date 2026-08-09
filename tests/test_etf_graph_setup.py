from tradingagents.dataflows.analysis_capabilities import (
    filter_etf_analysts,
    report_field_is_active,
)
from tradingagents.graph.setup import DEFAULT_ANALYSTS, ETF_ANALYSTS, resolve_analysts
from tradingagents.agents.quality_gate import create_quality_gate
from web.progress import stages_for


def test_etf_mode_has_only_etf_appropriate_analysts():
    assert resolve_analysts("etf") == ETF_ANALYSTS
    assert set(ETF_ANALYSTS) == {
        "market",
        "etf_liquidity",
        "etf_structure",
        "etf_index_news",
        "etf_compare",
    }
    assert not {"fundamentals", "hot_money", "lockup", "social"} & set(ETF_ANALYSTS)


def test_stock_mode_remains_unchanged():
    assert resolve_analysts("stock") == DEFAULT_ANALYSTS


def test_capability_probe_prunes_etf_analysts_and_stages():
    capabilities = [
        "price_history",
        "technical_indicators",
        "fund_profile",
        "index_news_policy",
    ]
    selected = resolve_analysts("etf", capabilities)
    assert selected == ("market", "etf_structure", "etf_index_news")
    assert "etf_liquidity" not in selected
    assert "etf_compare" not in selected

    stages = stages_for("etf", capabilities)
    stage_ids = [stage["id"] for stage in stages]
    assert "etf_liquidity" not in stage_ids
    assert "etf_compare" not in stage_ids
    assert "market" in stage_ids
    assert "quality_gate" in stage_ids


def test_peer_comparison_capability_keeps_compare_analyst():
    capabilities = [
        "price_history",
        "technical_indicators",
        "liquidity_metrics",
        "fund_profile",
        "shares_and_aum",
        "index_news_policy",
        "peer_comparison",
    ]
    assert "etf_compare" in resolve_analysts("etf", capabilities)
    assert report_field_is_active("etf_compare_report", capabilities)
    assert "etf_compare" in [stage["id"] for stage in stages_for("etf", capabilities)]


def test_filter_etf_analysts_helper():
    assert filter_etf_analysts(
        ETF_ANALYSTS, {"liquidity_metrics", "fund_profile"}
    ) == ("etf_liquidity", "etf_structure")


def test_report_field_activation_follows_capabilities():
    assert report_field_is_active("etf_liquidity_report", ["liquidity_metrics"])
    assert not report_field_is_active("etf_liquidity_report", ["fund_profile"])


def test_quality_gate_skips_unavailable_etf_fields():
    class _Resp:
        content = "ok"

    class _LLM:
        def invoke(self, *_args, **_kwargs):
            return _Resp()

    node = create_quality_gate(
        _LLM(),
        selected_analysts=list(ETF_ANALYSTS),
        analysis_mode="etf",
    )
    long_ok = (
        "| 指标 | 值 |\n| --- | --- |\n| 趋势 | 上行 |\n"
        + ("完整可用报告内容。" * 30)
    )
    state = {
        "trade_date": "2026-08-01",
        "company_of_interest": "510300",
        "analysis_capabilities": [
            "price_history",
            "technical_indicators",
            "fund_profile",
        ],
        "analysis_unavailable_capabilities": {
            "liquidity_metrics": "quote unavailable",
            "index_news_policy": "announcements unavailable",
        },
        "market_report": long_ok,
        "etf_profile_report": long_ok,
        "etf_liquidity_report": "公司营收与解禁",
        "etf_index_news_report": "",
    }
    result = node(state)
    assert "ETF流动性分析师" not in result["data_quality_summary"]
    assert "指数新闻与政策分析师" not in result["data_quality_summary"]
    assert "不可得数据" in result["data_quality_summary"]
    assert not result["data_quality_failed"]
