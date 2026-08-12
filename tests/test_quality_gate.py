"""Phase 5.3 quality gate: selected analysts, scaled threshold, block policy."""

from unittest.mock import MagicMock

from langgraph.graph import END

from tradingagents.agents.quality_gate import (
    ETF_REPORT_FIELDS,
    REPORT_FIELDS,
    _fail_threshold,
    _hard_check_report,
    create_quality_gate,
    find_etf_identity_conflicts,
    find_forbidden_term_hits,
)
from tradingagents.graph.conditional_logic import ConditionalLogic


def _state(reports: dict):
    base = {
        "trade_date": "2026-05-12",
        "company_of_interest": "600519",
        "data_quality_failed": False,
    }
    for field in REPORT_FIELDS.values():
        base[field] = ""
    base.update(reports)
    return base


def test_fail_threshold_scales():
    assert _fail_threshold(7) == 4
    assert _fail_threshold(3) == 2
    assert _fail_threshold(1) == 2


def test_only_selected_analysts_graded():
    llm = MagicMock()
    gate = create_quality_gate(llm, selected_analysts=["market", "news"])
    # Unselected analysts empty would have failed under the old always-grade-7 logic.
    long_ok = ("x" * 250) + "\n| a | b |\n| --- | --- |\n"
    result = gate(
        _state(
            {
                "market_report": long_ok,
                "news_report": long_ok,
            }
        )
    )
    assert result["data_quality_failed"] is False
    assert "技术分析师" in result["data_quality_summary"]
    assert "新闻分析师" in result["data_quality_summary"]
    assert "政策分析师" not in result["data_quality_summary"]


def test_selected_analysts_empty_reports_fail():
    llm = MagicMock()
    gate = create_quality_gate(llm, selected_analysts=["market", "news", "social"])
    result = gate(_state({}))
    assert result["data_quality_failed"] is True


def test_quality_gate_summary_has_no_internal_identifiers():
    llm = MagicMock()
    gate = create_quality_gate(llm, selected_analysts=["market", "news"])
    long_ok = ("x" * 250) + "\n| a | b |\n| --- | --- |\n"
    out = gate(
        _state(
            {
                "market_report": long_ok,
                "news_report": long_ok,
            }
        )
    )["data_quality_summary"]
    assert "data_quality_failed" not in out
    assert "fail_count" not in out
    assert "threshold" not in out
    assert "通过" in out


def test_block_policy_ends_graph():
    logic = ConditionalLogic(quality_gate_policy="block")
    assert logic.should_continue_after_quality_gate({"data_quality_failed": True}) is END
    assert (
        logic.should_continue_after_quality_gate({"data_quality_failed": False})
        == "Bull Researcher"
    )


def test_warn_policy_continues():
    logic = ConditionalLogic(quality_gate_policy="warn")
    assert (
        logic.should_continue_after_quality_gate({"data_quality_failed": True})
        == "Bull Researcher"
    )


def test_bundle_observe_only_is_not_promoted_by_subject_quality():
    llm = MagicMock()
    llm.invoke.return_value.content = "复审完成"
    gate = create_quality_gate(
        llm,
        selected_analysts=["market"],
        analysis_mode="etf",
        analysis_product="passive_equity_etf",
    )
    long_ok = ("ETF 自身行情分析。" * 30) + "\n| 项目 | 值 |\n| --- | --- |\n"
    result = gate(
        {
            "trade_date": "2026-05-12",
            "company_of_interest": "510300",
            "instrument_profile": {
                "security_type": "etf",
                "tracking_index_code": {"value": {"code": "000300"}},
            },
            "market_report": long_ok,
            "market_data_quality": {
                "grade": "A",
                "decision": "allow",
                "source_status": "PRIMARY_OK",
            },
            "market_data_decision": "observe_only",
        }
    )

    assert result["market_data_decision"] == "observe_only"
    assert result["data_quality_failed"] is False
    assert "组合决策：observe_only" in result["data_quality_summary"]


def test_etf_exclusion_list_does_not_trigger_forbidden_terms():
    report = """## 不可用维度

以下维度按规则不提供、不比较：
- 公司营收
- 龙虎榜数据
"""
    assert find_forbidden_term_hits(report) == []


def test_etf_identity_conflict_is_a_standalone_failure():
    assert find_etf_identity_conflicts("标的为深交所上市 LOF。") == ["LOF"]
    assert find_etf_identity_conflicts("该产品并非 LOF，而是 ETF。") == []
    long_report = (
        "标的为深交所上市 LOF。\n| 项目 | 值 |\n| --- | --- |\n"
        + ("完整报告。" * 50)
    )
    llm = MagicMock()
    gate = create_quality_gate(
        llm, selected_analysts=["market"], analysis_mode="etf"
    )
    result = gate(
        {
            "trade_date": "2026-05-12",
            "company_of_interest": "159326",
            "market_report": long_report,
        }
    )
    assert result["data_quality_failed"] is True
    assert "证券类型冲突" in result["data_quality_summary"]


def test_etf_missing_index_data_is_downgraded_to_c():
    report = (
        "跟踪指数行情未能取得有效数据，因此无法量化相对表现。\n"
        "| 项目 | 值 |\n| --- | --- |\n"
        + ("ETF 技术分析。" * 40)
    )
    grade, detail, _ = _hard_check_report("market", report, "etf")
    assert grade == "C"
    assert "跟踪指数行情缺失" in detail


def test_etf_stale_disclosure_is_downgraded_to_b():
    report = (
        "数据状态：`stale`，使用最近一期定期披露。\n"
        "| 项目 | 值 |\n| --- | --- |\n"
        + ("ETF 结构分析。" * 40)
    )
    grade, detail, _ = _hard_check_report("etf_structure", report, "etf")
    assert grade == "B"
    assert "使用过期披露数据" in detail


def test_etf_missing_optional_index_code_is_reported_but_not_blocked():
    long_ok = ("ETF 自身行情分析。" * 30) + "\n| 项目 | 值 |\n| --- | --- |\n"

    class _Response:
        content = "复审完成"

    llm = MagicMock()
    llm.invoke.return_value = _Response()
    gate = create_quality_gate(
        llm, selected_analysts=["market"], analysis_mode="etf"
    )
    result = gate(
        {
            "trade_date": "2026-05-12",
            "company_of_interest": "159326",
            "instrument_profile": {
                "security_type": "etf",
                "tracking_index_name": "中证电网设备主题指数",
                "tracking_index_code": None,
            },
            "market_report": long_ok,
        }
    )
    assert result["data_quality_failed"] is False
    assert "技术分析师: [C]" in result["data_quality_summary"]
    assert "本次仅分析 ETF 自身行情" in result["data_quality_summary"]
